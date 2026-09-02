"""Writes the per-paper output: pass JSON, findings CSV, synthesis report, run log."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from ..llm.provenance import RunProvenance
from ..schemas import Finding

FINDINGS_COLUMNS = [
    "pass", "severity", "category", "location", "quote", "description",
    "correction", "verdict", "url", "stability",
]


@dataclass
class RunPaths:
    root: Path
    paper_dir: Path
    run_dir: Path

    @property
    def findings_csv(self) -> Path:
        return self.run_dir / "findings.csv"

    @property
    def report_md(self) -> Path:
        return self.run_dir / "synthesis.md"

    @property
    def run_json(self) -> Path:
        return self.run_dir / "run.json"


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", name).strip("-.")
    return slug or "paper"


def prepare_paths(output_dir: Path, paper: Path, run_id: str) -> RunPaths:
    root = output_dir
    paper_dir = root / slugify(paper.stem)
    run_dir = paper_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    return RunPaths(root=root, paper_dir=paper_dir, run_dir=run_dir)


def write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(_encode(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _encode(data: Any) -> Any:
    if isinstance(data, BaseModel):
        return data.model_dump(mode="json")
    if isinstance(data, dict):
        return {k: _encode(v) for k, v in data.items()}
    if isinstance(data, (list, tuple)):
        return [_encode(item) for item in data]
    if isinstance(data, Path):
        return str(data)
    return data


def write_findings_csv(path: Path, findings: list[Finding]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FINDINGS_COLUMNS)
        writer.writeheader()
        for finding in findings:
            writer.writerow(
                {
                    "pass": finding.source_pass,
                    "severity": finding.severity.value,
                    "category": finding.category,
                    "location": finding.location,
                    "quote": " ".join(finding.quote.split()),
                    "description": " ".join(finding.description.split()),
                    "correction": finding.correction,
                    "verdict": finding.verdict,
                    "url": finding.url,
                    "stability": finding.stability.value,
                }
            )


def write_report(path: Path, markdown: str) -> None:
    path.write_text(markdown.rstrip() + "\n", encoding="utf-8")


def write_provenance(paths: RunPaths, provenance: RunProvenance) -> None:
    write_json(paths.run_json, provenance.as_dict())
    runs_log = paths.root / "runs.jsonl"
    runs_log.parent.mkdir(parents=True, exist_ok=True)
    with runs_log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(provenance.summary_row(), ensure_ascii=False) + "\n")


def fallback_report(
    findings: list[Finding], provenance: RunProvenance, pass_outputs: dict[str, Any]
) -> str:
    """Deterministic report, used when the synthesis call produces nothing."""
    lines = [
        "# Review report",
        "",
        "> The synthesis call did not return a report. This is the deterministic fallback, "
        "built from the pass outputs.",
        "",
        "## 1. Verdict",
        "",
        _verdict_line(findings),
        "",
        "## 2. Findings",
        "",
        "| Severity | Location | Description | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for finding in findings:
        severity = finding.severity.value
        if finding.stability.value == "unstable":
            severity += " (unstable)"
        evidence = finding.url or _cell(finding.quote)
        lines.append(
            f"| {severity} | {_cell(finding.location)} | {_cell(finding.description)} | {evidence} |"
        )
    if not findings:
        lines.append("| - | - | No findings were reported. | - |")

    lines += ["", "## 3. Reference audit", ""]
    pass3 = pass_outputs.get("pass3") or {}
    references = pass3.get("references") or []
    icons = {
        "verified": "OK", "metadata_mismatch": "MISMATCH", "not_found": "NOT FOUND",
        "retracted": "RETRACTED", "could_not_verify": "UNVERIFIED",
    }
    for ref in references:
        icon = icons.get(ref.get("status", ""), "?")
        detail = ref.get("mismatch_details") or ref.get("notes") or ""
        lines.append(f"- [{ref.get('index')}] {icon} - {ref.get('raw', '')[:180]} {detail}".rstrip())
    if not references:
        lines.append("- No bibliography entries were checked.")

    lines += ["", "## 4. Spelling and language", ""]
    typos = [f for f in findings if f.category == "spelling"]
    inconsistencies = [f for f in findings if f.category == "language"]
    lines.append(f"- Confirmed typos: {len(typos)}")
    lines.append(f"- Language and consistency findings: {len(inconsistencies)}")
    language = (pass_outputs.get("pass0") or {}).get("language", "unknown")
    lines.append(f"- Language variant reported by Pass 0: {language}")

    lines += ["", "## 5. Unverifiable items", ""]
    unverifiable = _unverifiable(pass_outputs)
    lines.extend(f"- {item}" for item in unverifiable) if unverifiable else lines.append(
        "- None recorded."
    )

    lines += ["", "## 6. Pass coverage", ""]
    lines.append(f"- Passes run: {', '.join(provenance.passes_run) or 'none'}")
    lines.append(f"- Search tool available: {provenance.search_tool_available}")
    lines.append(f"- Model: {provenance.model} ({provenance.quantization}) via {provenance.provider}")
    lines.append(f"- Prompt version: {provenance.prompt_version}, seed {provenance.seed}")
    for name, output in pass_outputs.items():
        for limitation in (output or {}).get("limitations", []) if isinstance(output, dict) else []:
            lines.append(f"- {name} limitation: {limitation}")
    if provenance.errors:
        for error in provenance.errors:
            lines.append(f"- error: {error}")
    return "\n".join(lines)


def _verdict_line(findings: list[Finding]) -> str:
    critical = [f for f in findings if f.severity.value == "critical"]
    major = [f for f in findings if f.severity.value == "major"]
    if critical:
        return (
            f"{len(critical)} critical and {len(major)} major findings were reported. "
            f"The most serious: {critical[0].description}"
        )
    if major:
        return (
            f"No critical findings. {len(major)} major findings were reported. "
            f"The most serious: {major[0].description}"
        )
    return f"No critical or major findings. {len(findings)} findings in total, all minor."


def _unverifiable(pass_outputs: dict[str, Any]) -> list[str]:
    items: list[str] = []
    pass2 = pass_outputs.get("pass2") or {}
    for check in pass2.get("number_checks", []) if isinstance(pass2, dict) else []:
        if check.get("verdict") == "could_not_verify":
            items.append(f"Pass 2 number check: {check.get('quantity', '')}")
    pass3 = pass_outputs.get("pass3") or {}
    unverified = [
        r for r in (pass3.get("references", []) if isinstance(pass3, dict) else [])
        if r.get("status") == "could_not_verify"
    ]
    if unverified:
        items.append(
            f"Pass 3: {len(unverified)} bibliography entries could not be verified; "
            "search each title and DOI by hand."
        )
    pass4 = pass_outputs.get("pass4") or {}
    unchecked = [
        c for c in (pass4.get("fact_checks", []) if isinstance(pass4, dict) else [])
        if c.get("verdict") == "could_not_verify"
    ]
    if unchecked:
        items.append(f"Pass 4: {len(unchecked)} external claims could not be verified.")
    return items


def _cell(text: str, limit: int = 220) -> str:
    flat = " ".join((text or "").split()).replace("|", "\\|")
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."
