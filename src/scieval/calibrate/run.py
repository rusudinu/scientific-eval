"""Calibration runner: review each paper, then measure agreement with its human review."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..config import Config
from ..pipeline import run_review
from ..report import slugify
from ..schemas import Finding
from .ground_truth import GroundTruthError, find_pairs, load
from .matcher import DEFAULT_THRESHOLD, MatchResult, match_findings
from .metrics import CalibrationReport, PaperReport, aggregate

Emit = Callable[[str], None]


def run_calibration(
    folder: Path,
    config: Config,
    *,
    repeats: int = 1,
    threshold: float = DEFAULT_THRESHOLD,
    reuse: bool = False,
    emit: Emit | None = None,
) -> CalibrationReport:
    """Run (or reuse) a review for every reviewed paper and score the agreement."""
    say: Emit = emit or (lambda _msg: None)
    pairs = find_pairs(folder)
    if not pairs:
        raise GroundTruthError(
            f"no paper/review pairs in {folder}; each X.pdf needs an X.review.json alongside it"
        )

    reports: list[PaperReport] = []
    settings: dict[str, Any] = {
        "threshold": threshold,
        "repeats": repeats,
        "provider": config.provider_name,
        "reuse": reuse,
    }

    for pdf, review_path in pairs:
        say(f"calibrating {pdf.name}")
        truth = load(pdf, review_path)
        predicted, run_id, error = _predictions(pdf, config, repeats, reuse, say, settings)
        result = (
            match_findings(truth.findings, predicted, threshold=threshold)
            if not error
            else MatchResult(matches=[], missed=truth.findings, spurious=[])
        )
        reports.append(
            PaperReport(
                paper=pdf.name,
                run_id=run_id,
                result=result,
                truth_count=len(truth.findings),
                predicted_count=len(predicted),
                error=error,
            )
        )
        if error:
            say(f"  {pdf.name}: run failed, excluded from the scores: {error}")
        else:
            say(
                f"  {pdf.name}: {len(result.matches)} matched, {len(result.missed)} missed, "
                f"{len(result.spurious)} spurious"
            )

    return aggregate(reports, settings)


def _predictions(
    pdf: Path, config: Config, repeats: int, reuse: bool, say: Emit, settings: dict[str, Any]
) -> tuple[list[Finding], str, str]:
    if reuse:
        cached = _load_cached(config.output_dir, pdf)
        if cached is not None:
            findings, run_id, provenance = cached
            say(f"  reusing run {run_id}")
            for key in ("model", "quantization", "prompt_version", "seed"):
                if provenance.get(key) is not None:
                    settings.setdefault(key, provenance[key])
            return findings, run_id, ""
        say("  no cached run found; running the pipeline")

    try:
        result = run_review(pdf, config, repeats=repeats, emit=lambda m: say(f"  {m}"))
    except Exception as exc:
        return [], "", str(exc)

    settings.setdefault("model", result.provenance.model)
    settings.setdefault("quantization", result.provenance.quantization)
    settings.setdefault("prompt_version", result.provenance.prompt_version)
    settings.setdefault("seed", result.provenance.seed)
    return result.findings, result.provenance.run_id, ""


def _load_cached(output_dir: Path, pdf: Path) -> tuple[list[Finding], str, dict[str, Any]] | None:
    """Latest completed run for this paper, if one exists."""
    paper_dir = output_dir / slugify(pdf.stem)
    pointer = paper_dir / "latest.txt"
    run_dir: Path | None = None
    if pointer.is_file():
        candidate = paper_dir / pointer.read_text(encoding="utf-8").strip()
        if candidate.is_dir():
            run_dir = candidate
    if run_dir is None:
        runs = sorted((d for d in paper_dir.glob("*") if d.is_dir()), reverse=True)
        run_dir = runs[0] if runs else None
    if run_dir is None:
        return None

    findings_file = run_dir / "findings.json"
    if not findings_file.is_file():
        return None
    data = json.loads(findings_file.read_text(encoding="utf-8"))
    findings = [Finding.model_validate(item) for item in data.get("findings", [])]

    run_file = run_dir / "run.json"
    provenance: dict[str, Any] = {}
    if run_file.is_file():
        try:
            provenance = json.loads(run_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            provenance = {}
    return findings, run_dir.name, provenance
