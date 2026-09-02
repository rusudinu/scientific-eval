"""Shared machinery for the passes: prompt loading, the paper context, the call runner."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from ..config import Config
from ..extract.bibliography import Reference
from ..extract.captions import Caption
from ..extract.pdf import Document
from ..extract.sections import Section
from ..llm.client import LLMClient
from ..llm.provenance import CallRecord, RunProvenance
from ..llm.structured import structured_call, text_call
from ..schemas import Pass0Output
from ..spellcheck.filters import Candidate

T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=32)
def _read_prompt(path_str: str) -> str:
    return Path(path_str).read_text(encoding="utf-8").strip()


def load_prompt(config: Config, name: str) -> str:
    path = config.prompts_dir / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"prompt file missing: {path}")
    return _read_prompt(str(path))


@dataclass
class PaperContext:
    """Everything extracted from the PDF before any model call."""

    path: Path
    document: Document
    sections: list[Section]
    references: list[Reference]
    captions: list[Caption]
    tables_text: str = ""
    candidates: dict[str, list[Candidate]] = field(default_factory=dict)
    inventory: Pass0Output | None = None
    language: str = "en"

    def section_by_label(self, label: str) -> Section | None:
        for section in self.sections:
            if section.label == label:
                return section
        return None

    def reviewable_sections(self) -> list[Section]:
        """Sections worth sending to Pass 1: skip references and boilerplate."""
        skip = {"references", "back_matter"}
        return [s for s in self.sections if s.kind not in skip and len(s.text.strip()) > 200]


class PassRunner:
    """Runs one structured call, records provenance, never raises on model failure."""

    def __init__(
        self,
        client: LLMClient,
        config: Config,
        provenance: RunProvenance,
        *,
        on_event: Any = None,
    ) -> None:
        self.client = client
        self.config = config
        self.provenance = provenance
        self._on_event = on_event
        self.system_prompt = load_prompt(config, "system")

    def _emit(self, message: str) -> None:
        if self._on_event:
            self._on_event(message)

    def model_for(self, pass_name: str) -> str:
        return self.client.resolve_model(self.config.model_for(pass_name))

    def structured(
        self,
        *,
        pass_name: str,
        label: str,
        task_prompt: str,
        payload: str,
        schema: type[T],
    ) -> T | None:
        model = self.model_for(pass_name)
        self._emit(f"{label} -> {model}")
        user = f"{task_prompt}\n\n=== INPUT ===\n{payload}"
        result = structured_call(
            self.client, model=model, system=self.system_prompt, user=user, schema=schema,
            schema_name=schema.__name__,
        )
        self.provenance.add_call(
            CallRecord(
                pass_name=pass_name, label=label, model=result.model or model, mode=result.mode,
                ok=result.ok, attempts=result.attempts, duration_s=result.duration_s,
                usage=result.usage, error=result.error,
            )
        )
        if not result.ok:
            self.provenance.errors.append(f"{label}: {result.error}")
            self._emit(f"{label} failed: {result.error}")
        return result.value

    def markdown(self, *, pass_name: str, label: str, task_prompt: str, payload: str) -> str:
        model = self.model_for(pass_name)
        self._emit(f"{label} -> {model}")
        user = f"{task_prompt}\n\n=== INPUT ===\n{payload}"
        try:
            result = text_call(self.client, model=model, system=self.system_prompt, user=user)
        except Exception as exc:
            self.provenance.add_call(
                CallRecord(
                    pass_name=pass_name, label=label, model=model, mode="text", ok=False,
                    attempts=1, duration_s=0.0, error=str(exc),
                )
            )
            self.provenance.errors.append(f"{label}: {exc}")
            return ""
        self.provenance.add_call(
            CallRecord(
                pass_name=pass_name, label=label, model=result.model, mode="text", ok=True,
                attempts=1, duration_s=result.duration_s, usage=result.usage,
            )
        )
        return result.text


def as_json(data: Any, *, limit: int | None = None) -> str:
    """Compact JSON for prompt payloads, truncated with an explicit marker."""
    text = json.dumps(data, ensure_ascii=False, indent=1, default=str)
    if limit and len(text) > limit:
        return text[:limit] + "\n... [TRUNCATED]"
    return text


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n... [TRUNCATED: section longer than the configured limit]"
