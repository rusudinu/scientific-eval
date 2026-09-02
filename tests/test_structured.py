"""Structured output: schema shaping, JSON recovery, fallbacks and repair."""

from __future__ import annotations

import json

import pytest

from scieval.config import load_config
from scieval.llm.client import LLMClient, LLMError
from scieval.llm.structured import (
    extract_json,
    response_format_for,
    strict_json_schema,
    structured_call,
)
from scieval.schemas import Pass1Output


class FakeClient:
    """Stands in for LLMClient; returns queued replies or raises queued errors."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def chat(self, messages, *, model, response_format=None, seed=None, temperature=None,
             max_tokens=None):
        from scieval.llm.client import ChatResult

        self.calls.append(
            {"messages": messages, "response_format": response_format, "model": model}
        )
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(text=reply, model=model, usage={"total_tokens": 10}, duration_s=0.1)


def _valid_payload() -> str:
    return json.dumps(
        {
            "section": "1 Introduction",
            "spellcheck_triage": [
                {"token": "allready", "classification": "typo", "correction": "already",
                 "quote": "was allready shown", "location": "1 Introduction"}
            ],
            "findings": [],
            "limitations": [],
        }
    )


def test_strict_schema_inlines_refs_and_requires_every_property():
    schema = strict_json_schema(Pass1Output)
    text = json.dumps(schema)
    assert "$ref" not in text and "$defs" not in text
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    triage = schema["properties"]["spellcheck_triage"]["items"]
    assert triage["properties"]["classification"]["enum"] == ["typo", "domain_term", "inconsistent"]
    assert "default" not in json.dumps(schema)


def test_response_format_is_strict_json_schema():
    fmt = response_format_for(Pass1Output, "Pass1Output")
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["name"] == "Pass1Output"


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1}',
        '```json\n{"a": 1}\n```',
        'Sure, here you go:\n```\n{"a": 1}\n```\nHope that helps.',
        '<think>let me think about this</think>{"a": 1}',
        'Preamble text {"a": 1} trailing text',
    ],
)
def test_extract_json_recovers_the_object(text):
    assert json.loads(extract_json(text)) == {"a": 1}


def test_structured_call_parses_a_valid_reply():
    client = FakeClient([_valid_payload()])
    result = structured_call(
        client, model="m", system="sys", user="usr", schema=Pass1Output
    )
    assert result.ok is True
    assert result.mode == "json_schema"
    assert result.attempts == 1
    assert result.value.spellcheck_triage[0].correction == "already"


def test_structured_call_falls_back_when_json_schema_is_rejected():
    client = FakeClient([LLMError("400 response_format not supported"), _valid_payload()])
    result = structured_call(client, model="m", system="s", user="u", schema=Pass1Output)
    assert result.ok is True
    assert result.mode == "json_object"
    assert client.calls[1]["response_format"] == {"type": "json_object"}


def test_structured_call_repairs_an_invalid_reply():
    client = FakeClient(['{"section": 5}', _valid_payload()])
    result = structured_call(client, model="m", system="s", user="u", schema=Pass1Output)
    assert result.ok is True
    assert result.mode == "json_schema+repair"
    assert result.attempts == 2
    # The repair turn quotes the validation error back to the model.
    repair_prompt = client.calls[1]["messages"][-1]["content"]
    assert "not valid against the required schema" in repair_prompt


def test_structured_call_reports_failure_without_raising():
    client = FakeClient(["nonsense"] * 6)
    result = structured_call(client, model="m", system="s", user="u", schema=Pass1Output)
    assert result.ok is False
    assert result.mode == "failed"
    assert result.value is None
    assert result.error


def test_connection_errors_stop_immediately():
    client = FakeClient([LLMError("Connection refused")])
    result = structured_call(client, model="m", system="s", user="u", schema=Pass1Output)
    assert result.ok is False
    assert result.attempts == 1
    assert "Connection refused" in result.error


def _sdk_client(handler):
    """Build an OpenAI-SDK HTTP client backed by a mock transport.

    The SDK vendors its own httpx build (`httpx2`), so respx cannot intercept it
    and the transport has to come from that module.
    """
    httpx2 = pytest.importorskip("httpx2")
    return httpx2.Client(transport=httpx2.MockTransport(handler))


def test_client_sends_seed_and_temperature():
    import httpx2

    captured: dict = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx2.Response(
            200,
            json={
                "id": "1", "object": "chat.completion", "created": 0, "model": "test-model",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "{}"},
                     "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
            },
        )

    config = load_config()
    config.seed = 99
    config.temperature = 0.0
    client = LLMClient(config, http_client=_sdk_client(handler))
    result = client.chat([{"role": "user", "content": "hi"}], model="test-model")

    assert captured["body"]["seed"] == 99
    assert captured["body"]["temperature"] == 0.0
    assert result.usage["total_tokens"] == 7


def test_resolve_model_uses_the_first_reported_model():
    import httpx2

    def handler(request):
        return httpx2.Response(
            200,
            json={"object": "list", "data": [
                {"id": "first-model", "object": "model"},
                {"id": "second-model", "object": "model"},
            ]},
        )

    client = LLMClient(load_config(), http_client=_sdk_client(handler))
    assert client.resolve_model(None) == "first-model"
    assert client.resolve_model("explicit") == "explicit"


def test_list_models_error_is_wrapped():
    import httpx2

    def handler(request):
        raise httpx2.ConnectError("refused")

    client = LLMClient(load_config(), http_client=_sdk_client(handler))
    with pytest.raises(LLMError, match="cannot list models"):
        client.list_models()


def test_resolve_model_skips_embedding_models():
    import httpx2

    def handler(request):
        return httpx2.Response(
            200,
            json={"object": "list", "data": [
                {"id": "text-embedding-nomic-embed-text-v1.5", "object": "model"},
                {"id": "qwen/qwen3.5-9b", "object": "model"},
            ]},
        )

    client = LLMClient(load_config(), http_client=_sdk_client(handler))
    assert client.resolve_model(None) == "qwen/qwen3.5-9b"


def test_resolve_model_errors_when_only_embeddings_are_loaded():
    import httpx2
    from scieval.config import ConfigError

    def handler(request):
        return httpx2.Response(
            200,
            json={"object": "list", "data": [{"id": "text-embedding-3", "object": "model"}]},
        )

    client = LLMClient(load_config(), http_client=_sdk_client(handler))
    with pytest.raises(ConfigError, match="only embedding models"):
        client.resolve_model(None)


def test_extract_json_stops_at_the_end_of_the_object():
    """Trailing commentary containing braces must not break the parse."""
    text = '{"section": "1 Introduction", "findings": []} Note that {} means no findings.'
    assert json.loads(extract_json(text)) == {"section": "1 Introduction", "findings": []}


def test_extra_keys_do_not_discard_a_usable_reply():
    """A model that adds a stray key still produced the findings; keep them."""
    payload = json.loads(_valid_payload())
    payload["grammar"] = ["some extra commentary the model invented"]
    client = FakeClient([json.dumps(payload)])
    result = structured_call(client, model="m", system="s", user="u", schema=Pass1Output)
    assert result.ok is True
    assert result.attempts == 1
    assert result.value.spellcheck_triage[0].token == "allready"


def test_a_context_length_error_is_not_retried_unconstrained():
    """Degrading to free-form output on a context overflow hides the real problem."""
    client = FakeClient(
        [LLMError("Error code: 400 - the prompt exceeds the model's context length")]
    )
    result = structured_call(client, model="m", system="s", user="u", schema=Pass1Output)
    assert result.ok is False
    assert result.mode == "context_exceeded"
    assert result.attempts == 1
    assert "larger context" in result.error
    # Only one call was made: no silent fallback to json_object.
    assert len(client.calls) == 1
