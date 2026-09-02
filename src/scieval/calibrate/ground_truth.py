"""Loading human reviews used as calibration ground truth."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ..schemas import Finding, Severity

REVIEW_SUFFIXES = (".review.json", ".findings.json")


class GroundTruthError(RuntimeError):
    """Raised when a ground-truth file cannot be read."""


@dataclass
class GroundTruth:
    paper: Path
    review_path: Path
    findings: list[Finding]
    notes: str = ""


def find_pairs(folder: Path) -> list[tuple[Path, Path]]:
    """Every PDF in the folder that has a matching review file."""
    pairs: list[tuple[Path, Path]] = []
    for pdf in sorted(folder.glob("*.pdf")):
        for suffix in REVIEW_SUFFIXES:
            candidate = pdf.with_suffix("").with_name(pdf.stem + suffix)
            if candidate.is_file():
                pairs.append((pdf, candidate))
                break
    return pairs


def load(pdf: Path, review_path: Path) -> GroundTruth:
    try:
        data = json.loads(review_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GroundTruthError(f"{review_path.name}: invalid JSON: {exc}") from exc

    if isinstance(data, list):
        raw_findings, notes = data, ""
    elif isinstance(data, dict):
        raw_findings = data.get("findings", [])
        notes = str(data.get("notes", ""))
    else:
        raise GroundTruthError(f"{review_path.name}: expected an object or a list")

    if not isinstance(raw_findings, list):
        raise GroundTruthError(f"{review_path.name}: 'findings' must be a list")

    findings: list[Finding] = []
    for i, item in enumerate(raw_findings):
        if not isinstance(item, dict):
            raise GroundTruthError(f"{review_path.name}: finding {i} is not an object")
        findings.append(_coerce(item, review_path, i))
    return GroundTruth(paper=pdf, review_path=review_path, findings=findings, notes=notes)


def _coerce(item: dict, review_path: Path, position: int) -> Finding:
    payload = {
        "severity": item.get("severity", "major"),
        "category": str(item.get("category", "")).strip(),
        "location": str(item.get("location", "")),
        "quote": str(item.get("quote", "")),
        "description": str(item.get("description", "")),
        "correction": str(item.get("correction", "")),
        "source_pass": str(item.get("pass", item.get("source_pass", ""))),
        "url": str(item.get("url", "")),
    }
    try:
        return Finding.model_validate(payload)
    except ValidationError as exc:
        allowed = ", ".join(s.value for s in Severity)
        raise GroundTruthError(
            f"{review_path.name}: finding {position} is invalid ({exc.errors()[0]['msg']}); "
            f"severity must be one of: {allowed}"
        ) from exc


TEMPLATE = {
    "paper": "example.pdf",
    "notes": "Reviewed by <name> on <date>. One entry per issue.",
    "findings": [
        {
            "severity": "critical",
            "category": "numbers",
            "location": "4 Results, p. 6",
            "quote": "accuracy of 94.2% on the held-out set",
            "description": "Abstract reports 94.2% but Table 3 reports 91.7% for the same run.",
            "correction": "",
        },
        {
            "severity": "minor",
            "category": "spelling",
            "location": "1 Introduction, p. 1",
            "quote": "a signifcant improvement",
            "description": "Misspelling of 'significant'.",
            "correction": "significant",
        },
    ],
}
