"""Structured JSON output: json_schema when the server supports it, with fallbacks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from .client import ChatResult, LLMClient, LLMError

T = TypeVar("T", bound=BaseModel)

FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
# Reasoning models emit a think block before the answer.
THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


@dataclass
class StructuredResult:
    """The parsed value plus everything the run log needs about how it was obtained."""

    value: Any
    ok: bool
    mode: str  # json_schema | json_object | text | failed
    attempts: int
    raw_text: str = ""
    error: str = ""
    usage: dict[str, int] = field(default_factory=dict)
    duration_s: float = 0.0
    model: str = ""

    def meta(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "attempts": self.attempts,
            "model": self.model,
            "usage": self.usage,
            "duration_s": self.duration_s,
            "error": self.error,
        }


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic schema flattened into the strict subset servers accept.

    Inlines `$ref`/`$defs`, marks every property required and forbids extra keys,
    which is what OpenAI-style `json_schema` strict mode and LM Studio's grammar
    engine both expect.
    """
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})
    resolved = _resolve(schema, defs, set())
    return _strictify(resolved)


def _resolve(node: Any, defs: dict[str, Any], seen: frozenset[str] | set[str]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.split("/")[-1]
            if name in seen:
                # Recursive model: degrade to a free-form object rather than loop.
                return {"type": "object"}
            target = defs.get(name, {})
            merged = _resolve(target, defs, set(seen) | {name})
            extra = {k: v for k, v in node.items() if k != "$ref"}
            if isinstance(merged, dict):
                merged = {**merged, **extra}
            return merged
        return {k: _resolve(v, defs, seen) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve(item, defs, seen) for item in node]
    return node


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _strictify(v) for k, v in node.items() if k not in {"default", "$defs"}}
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
        return node
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    return node


def response_format_for(model: type[BaseModel], name: str | None = None) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name or model.__name__,
            "strict": True,
            "schema": strict_json_schema(model),
        },
    }


def extract_json(text: str) -> str:
    """Pull the JSON object out of a reply that may carry fences or commentary."""
    cleaned = THINK.sub("", text).strip()
    fenced = FENCE.search(cleaned)
    if fenced:
        cleaned = fenced.group(1).strip()
    start = cleaned.find("{")
    if start == -1:
        return cleaned
    # Decode from the first brace so trailing commentary (which may itself contain
    # braces) does not turn a good reply into a parse error and a wasted repair turn.
    try:
        _, end = json.JSONDecoder().raw_decode(cleaned[start:])
        return cleaned[start : start + end]
    except json.JSONDecodeError:
        last = cleaned.rfind("}")
        return cleaned[start : last + 1] if last > start else cleaned


def _parse(text: str, schema: type[T]) -> tuple[T | None, str]:
    payload = extract_json(text)
    if not payload:
        return None, "empty response"
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, f"expected a JSON object, got {type(data).__name__}"
    try:
        return schema.model_validate(data), ""
    except ValidationError as exc:
        return None, _short_validation_error(exc)


def _short_validation_error(exc: ValidationError, limit: int = 8) -> str:
    lines = []
    for error in exc.errors()[:limit]:
        location = ".".join(str(p) for p in error["loc"])
        lines.append(f"{location}: {error['msg']}")
    extra = len(exc.errors()) - limit
    if extra > 0:
        lines.append(f"...and {extra} more")
    return "; ".join(lines)


def structured_call(
    client: LLMClient,
    *,
    model: str,
    system: str,
    user: str,
    schema: type[T],
    schema_name: str | None = None,
    max_tokens: int | None = None,
) -> StructuredResult:
    """One pass call: ask for JSON, validate it, repair once if needed."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    attempts = 0
    last_text = ""
    last_error = ""
    usage_total: dict[str, int] = {}
    duration_total = 0.0
    used_model = model

    modes: list[tuple[str, dict[str, Any] | None]] = [
        ("json_schema", response_format_for(schema, schema_name)),
        ("json_object", {"type": "json_object"}),
        ("text", None),
    ]

    for mode, response_format in modes:
        try:
            attempts += 1
            result = client.chat(
                messages,
                model=model,
                response_format=response_format,
                max_tokens=max_tokens,
            )
        except LLMError as exc:
            last_error = str(exc)
            if _is_context_error(exc):
                return StructuredResult(
                    value=None,
                    ok=False,
                    mode="context_exceeded",
                    attempts=attempts,
                    error=(
                        f"{exc}\nThe payload does not fit the model's context. Load the model "
                        f"with a larger context, use a smaller model input by lowering "
                        f"[limits] in scieval.toml, or pick a longer-context model."
                    ),
                    usage=usage_total,
                    duration_s=duration_total,
                    model=used_model,
                )
            # A rejected response_format is a server capability problem: try the
            # next mode. Anything else (connection, auth) will fail the same way.
            if not _is_format_error(exc):
                return StructuredResult(
                    value=None,
                    ok=False,
                    mode="failed",
                    attempts=attempts,
                    error=last_error,
                    usage=usage_total,
                    duration_s=duration_total,
                    model=used_model,
                )
            continue

        used_model = result.model
        duration_total += result.duration_s
        _merge_usage(usage_total, result.usage)
        last_text = result.text

        value, error = _parse(result.text, schema)
        if value is not None:
            return StructuredResult(
                value=value,
                ok=True,
                mode=mode,
                attempts=attempts,
                raw_text=result.text,
                usage=usage_total,
                duration_s=duration_total,
                model=used_model,
            )
        last_error = error

        repaired, repair_result = _repair(
            client,
            model=model,
            messages=messages,
            previous=result,
            error=error,
            schema=schema,
            response_format=response_format,
            max_tokens=max_tokens,
        )
        attempts += 1
        if repair_result is not None:
            duration_total += repair_result.duration_s
            _merge_usage(usage_total, repair_result.usage)
            last_text = repair_result.text
        if repaired is not None:
            return StructuredResult(
                value=repaired,
                ok=True,
                mode=f"{mode}+repair",
                attempts=attempts,
                raw_text=last_text,
                usage=usage_total,
                duration_s=duration_total,
                model=used_model,
            )

    return StructuredResult(
        value=None,
        ok=False,
        mode="failed",
        attempts=attempts,
        raw_text=last_text,
        error=last_error or "no valid JSON produced",
        usage=usage_total,
        duration_s=duration_total,
        model=used_model,
    )


def _repair(
    client: LLMClient,
    *,
    model: str,
    messages: list[dict[str, str]],
    previous: ChatResult,
    error: str,
    schema: type[T],
    response_format: dict[str, Any] | None,
    max_tokens: int | None,
) -> tuple[T | None, ChatResult | None]:
    """One corrective turn quoting the validation error."""
    repair_messages = [
        *messages,
        {"role": "assistant", "content": previous.text[:6000]},
        {
            "role": "user",
            "content": (
                "Your previous reply was not valid against the required schema: "
                f"{error}\n\nReturn the corrected JSON object only. No prose, no code fences, "
                "no explanation. Every required field must be present."
            ),
        },
    ]
    try:
        result = client.chat(
            repair_messages, model=model, response_format=response_format, max_tokens=max_tokens
        )
    except LLMError:
        return None, None
    value, _ = _parse(result.text, schema)
    return value, result


# A context-length rejection also arrives as a 400. Retrying it without the schema
# only trades a clear error for an unconstrained reply, so it must not look like a
# response_format problem.
CONTEXT_MARKERS = (
    "context length",
    "context window",
    "maximum context",
    "context_length",
    "too long",
    "too many tokens",
    "exceeds",
    "reduce the length",
    "prompt is too",
)
FORMAT_MARKERS = (
    "response_format",
    "json_schema",
    "json schema",
    "unsupported",
    "not supported",
    "invalid_request_error",
    "422",
    "schema",
)


def _is_context_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CONTEXT_MARKERS)


def _is_format_error(exc: Exception) -> bool:
    if _is_context_error(exc):
        return False
    text = str(exc).lower()
    return any(marker in text for marker in FORMAT_MARKERS)


def _merge_usage(total: dict[str, int], addition: dict[str, int]) -> None:
    for key, value in addition.items():
        total[key] = total.get(key, 0) + value


def text_call(
    client: LLMClient, *, model: str, system: str, user: str, max_tokens: int | None = None
) -> ChatResult:
    """Plain-text call, used by the synthesis pass which returns Markdown."""
    return client.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        max_tokens=max_tokens,
    )
