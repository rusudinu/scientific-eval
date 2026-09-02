"""Per-run provenance: what model, which quantization, which prompts, which seed."""

from __future__ import annotations

import hashlib
import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import __version__
from ..config import Config


@dataclass
class CallRecord:
    """One LLM call, logged so a run can be audited after the fact."""

    pass_name: str
    label: str
    model: str
    mode: str
    ok: bool
    attempts: int
    duration_s: float
    usage: dict[str, int] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "pass": self.pass_name,
            "label": self.label,
            "model": self.model,
            "mode": self.mode,
            "ok": self.ok,
            "attempts": self.attempts,
            "duration_s": self.duration_s,
            "usage": self.usage,
            "error": self.error,
        }


@dataclass
class RunProvenance:
    """Everything needed to reproduce or compare a run."""

    run_id: str
    paper: str
    paper_sha256: str
    provider: str
    base_url: str
    model: str
    quantization: str
    model_info: dict[str, Any]
    prompt_version: str
    prompt_hashes: dict[str, str]
    seed: int
    temperature: float
    repeats: int
    reference_provider: str
    web_search_provider: str
    search_tool_available: bool
    started_at: str
    tool_version: str = __version__
    python_version: str = field(default_factory=platform.python_version)
    finished_at: str = ""
    duration_s: float = 0.0
    passes_run: list[str] = field(default_factory=list)
    calls: list[CallRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def add_call(self, record: CallRecord) -> None:
        self.calls.append(record)

    @property
    def total_usage(self) -> dict[str, int]:
        total: dict[str, int] = {}
        for call in self.calls:
            for key, value in call.usage.items():
                total[key] = total.get(key, 0) + value
        return total

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "paper": self.paper,
            "paper_sha256": self.paper_sha256,
            "tool_version": self.tool_version,
            "python_version": self.python_version,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "quantization": self.quantization,
            "model_info": self.model_info,
            "prompt_version": self.prompt_version,
            "prompt_hashes": self.prompt_hashes,
            "seed": self.seed,
            "temperature": self.temperature,
            "repeats": self.repeats,
            "reference_provider": self.reference_provider,
            "web_search_provider": self.web_search_provider,
            "search_tool_available": self.search_tool_available,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": self.duration_s,
            "passes_run": self.passes_run,
            "total_usage": self.total_usage,
            "calls": [c.as_dict() for c in self.calls],
            "errors": self.errors,
        }

    def summary_row(self) -> dict[str, Any]:
        """Compact line appended to out/runs.jsonl."""
        return {
            "run_id": self.run_id,
            "paper": self.paper,
            "started_at": self.started_at,
            "provider": self.provider,
            "model": self.model,
            "quantization": self.quantization,
            "prompt_version": self.prompt_version,
            "seed": self.seed,
            "temperature": self.temperature,
            "repeats": self.repeats,
            "search_tool_available": self.search_tool_available,
            "passes_run": self.passes_run,
            "duration_s": self.duration_s,
            "total_usage": self.total_usage,
            "errors": len(self.errors),
        }


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def make_run_id(seed: int) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-s{seed}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prompt_version(prompts_dir: Path) -> str:
    version_file = prompts_dir / "VERSION"
    if version_file.is_file():
        return version_file.read_text(encoding="utf-8").strip()
    return "unknown"


def prompt_hashes(prompts_dir: Path) -> dict[str, str]:
    """sha256 of every prompt file, so a prompt edit is visible in the run log."""
    hashes: dict[str, str] = {}
    for path in sorted(prompts_dir.glob("*.md")):
        if path.name == "paper-review-prompts.md":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[path.name] = digest[:16]
    return hashes


def build_provenance(
    config: Config,
    *,
    paper: Path,
    model: str,
    model_info: dict[str, Any],
    repeats: int,
    search_tool_available: bool,
    quantization_override: str | None = None,
) -> RunProvenance:
    quantization = quantization_override or model_info.get("quantization") or "unknown"
    return RunProvenance(
        run_id=make_run_id(config.seed),
        paper=paper.name,
        paper_sha256=sha256_file(paper),
        provider=config.provider_name,
        base_url=config.provider.base_url,
        model=model,
        quantization=str(quantization),
        model_info=model_info,
        prompt_version=prompt_version(config.prompts_dir),
        prompt_hashes=prompt_hashes(config.prompts_dir),
        seed=config.seed,
        temperature=config.temperature,
        repeats=repeats,
        reference_provider=config.search.reference_provider,
        web_search_provider=config.search.web_provider,
        search_tool_available=search_tool_available,
        started_at=now_iso(),
    )
