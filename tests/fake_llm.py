"""A scripted stand-in for LLMClient, so the pipeline can be tested without a server."""

from __future__ import annotations

import json
from typing import Any

from scieval.llm.client import ChatResult


def _pass0() -> dict:
    return {
        "language": "en-GB",
        "title": "Latency Effects of Adaptive Caching in Distributed Key-Value Stores",
        "sections": [
            {"number": "", "title": "Abstract", "pages": "1"},
            {"number": "1", "title": "Introduction", "pages": "1"},
            {"number": "2", "title": "Related Work", "pages": "1"},
            {"number": "3", "title": "Method", "pages": "1"},
            {"number": "4", "title": "Results", "pages": "1"},
            {"number": "5", "title": "Discussion", "pages": "1-2"},
            {"number": "6", "title": "Conclusion", "pages": "2"},
            {"number": "", "title": "References", "pages": "2"},
        ],
        "research_questions_or_hypotheses": ["Does adaptive caching reduce mean latency?"],
        "figures": [{"id": "Figure 1", "caption": "Hit rate over time", "referenced_in_text": False}],
        "tables": [{"id": "Table 1", "caption": "Mean latency by policy", "referenced_in_text": True}],
        "key_numbers": [
            {"value": "31.4%", "meaning": "claimed latency reduction",
             "locations": ["Abstract", "6 Conclusion"]},
            {"value": "27.2%", "meaning": "computed latency reduction", "locations": ["4 Results"]},
            {"value": "240", "meaning": "number of traces", "locations": ["Abstract", "3 Method"]},
            {"value": "200", "meaning": "traces in final evaluation", "locations": ["4 Results"]},
        ],
        "bibliography": [{"index": i, "raw": f"Reference {i}"} for i in range(1, 5)],
        "limitations": [],
    }


def _pass1() -> dict:
    return {
        "section": "1 Introduction",
        "spellcheck_triage": [
            {"token": "allready", "classification": "typo", "correction": "already",
             "quote": "was allready shown to be promising", "location": "1 Introduction, p. 1"},
            {"token": "resizes", "classification": "domain_term", "correction": "",
             "quote": "resizes the cache online", "location": "1 Introduction, p. 1"},
        ],
        "findings": [
            {"severity": "minor", "category": "figure_table",
             "location": "4 Results, p. 1", "quote": "Figure 1. Hit rate over time",
             "description": "Figure 1 is never referenced in the text.", "correction": ""}
        ],
        "limitations": [],
    }


def _pass2() -> dict:
    return {
        "number_checks": [
            {"quantity": "latency reduction", "locations": ["Abstract", "4 Results"],
             "values": ["31.4%", "27.2%"],
             "recomputation": "(8.10 - 5.90) / 8.10 = 0.2716 = 27.2%, not 31.4%",
             "verdict": "verified_incorrect"},
            {"quantity": "trace count", "locations": ["Abstract", "4 Results"],
             "values": ["240", "200"], "recomputation": "240 != 200; exclusions are not explained",
             "verdict": "verified_incorrect"},
        ],
        "claim_checks": [
            {"claim_quote": "Adaptive caching therefore causes lower tail latency",
             "location": "4 Results", "supporting_evidence": "Table 1 reports mean latency only",
             "verdict": "overreach",
             "explanation": "Causal language for a correlational comparison of means."}
        ],
        "research_question_alignment": [
            {"question": "Does adaptive caching reduce mean latency?",
             "what_was_actually_tested": "Mean latency on 200 of 240 traces",
             "gap": "Tail latency is claimed but never measured."}
        ],
        "findings": [
            {"severity": "critical", "category": "numbers", "location": "Abstract, p. 1",
             "quote": "a mean latency reduction of 31.4%",
             "description": "The abstract claims 31.4% but Table 1 gives 27.2%."},
            {"severity": "major", "category": "claims", "location": "4 Results, p. 1",
             "quote": "Adaptive caching therefore causes lower tail latency",
             "description": "Causal claim about tail latency with no tail-latency measurement."},
        ],
        "limitations": [],
    }


def _pass3(indexes: list[int]) -> dict:
    return {
        "search_tool_available": True,
        "references": [
            {"index": i, "raw": f"Reference {i}",
             "status": "verified" if i != 4 else "not_found",
             "found_at": "https://doi.org/10.1000/x" if i != 4 else "",
             "mismatch_details": "", "citing_sentences": [],
             "supports_claim": "yes" if i != 4 else "could_not_check", "notes": ""}
            for i in indexes
        ],
        "missing_citations": [],
        "limitations": [],
    }


def _pass3_missing() -> dict:
    return {
        "search_tool_available": True,
        "references": [],
        "missing_citations": [
            {"quote": "The first commercial key-value store was released in 1979.",
             "location": "1 Introduction, p. 1", "why_needed": "A historical fact needs a source."}
        ],
        "limitations": [],
    }


def _pass4_claims() -> dict:
    return {
        "claims": [
            {"claim_quote": "The first commercial key-value store was released in 1979.",
             "location": "1 Introduction, p. 1",
             "search_query": "first commercial key-value store release year"}
        ],
        "main_result_query": "adaptive cache sizing latency distributed key-value store",
        "limitations": [],
    }


class FakeLLMClient:
    """Returns a canned, schema-valid reply based on the requested json_schema name."""

    def __init__(self, config=None, **_kwargs) -> None:
        self.config = config
        self.calls: list[dict[str, Any]] = []
        self.reference_batches: list[list[int]] = []

    def resolve_model(self, requested: str | None) -> str:
        return requested or "fake-model"

    def list_models(self) -> list[dict[str, Any]]:
        return [{"id": "fake-model", "object": "model"}]

    def native_model_info(self, model_id: str) -> dict[str, Any]:
        return {"quantization": "Q4_K_M", "context_length": 8192, "source": "fake"}

    def chat(self, messages, *, model, response_format=None, seed=None, temperature=None,
             max_tokens=None) -> ChatResult:
        user = messages[-1]["content"]
        self.calls.append({"model": model, "response_format": response_format, "user": user})
        payload = self._reply(response_format, user)
        return ChatResult(
            text=payload, model=model, usage={"total_tokens": 100}, duration_s=0.01,
            finish_reason="stop",
        )

    def _reply(self, response_format, user: str) -> str:
        if response_format is None:
            return "# Review report\n\n## 1. Verdict\n\nThe headline number is wrong.\n"
        name = (response_format.get("json_schema") or {}).get("name", "")
        if name == "Pass0Output":
            return json.dumps(_pass0())
        if name == "Pass1Output":
            return json.dumps(_pass1())
        if name == "Pass2Output":
            return json.dumps(_pass2())
        if name == "Pass4ClaimsOutput":
            return json.dumps(_pass4_claims())
        if name == "Pass4Output":
            return json.dumps({
                "search_tool_available": True, "fact_checks": [], "missing_engagement": [],
                "limitations": [],
            })
        if name == "Pass3Output":
            if "missing_citations" in user and "list ONLY claims" in user:
                return json.dumps(_pass3_missing())
            indexes = _indexes_in(user)
            self.reference_batches.append(indexes)
            return json.dumps(_pass3(indexes))
        return "{}"


def _indexes_in(user: str) -> list[int]:
    import re

    return sorted({int(m) for m in re.findall(r'"index":\s*(\d+)', user)})
