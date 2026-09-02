"""Agreement metrics between model findings and human reviews."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..schemas import Finding
from .matcher import MatchResult

PAPER_COLUMNS = [
    "paper",
    "run_id",
    "truth_findings",
    "model_findings",
    "matched",
    "missed",
    "spurious",
    "precision",
    "recall",
    "f1",
    "severity_agreement",
    "error",
]


@dataclass
class Scores:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def recall(self) -> float:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


@dataclass
class PaperReport:
    paper: str
    run_id: str
    result: MatchResult
    truth_count: int
    predicted_count: int
    error: str = ""

    @property
    def scores(self) -> Scores:
        return Scores(
            true_positives=len(self.result.matches),
            false_positives=len(self.result.spurious),
            false_negatives=len(self.result.missed),
        )

    @property
    def severity_agreement(self) -> float:
        if not self.result.matches:
            return 0.0
        agreed = sum(1 for m in self.result.matches if m.severity_agrees)
        return agreed / len(self.result.matches)

    def row(self) -> dict[str, Any]:
        scores = self.scores
        return {
            "paper": self.paper,
            "run_id": self.run_id,
            "truth_findings": self.truth_count,
            "model_findings": self.predicted_count,
            "matched": len(self.result.matches),
            "missed": len(self.result.missed),
            "spurious": len(self.result.spurious),
            "precision": round(scores.precision, 3),
            "recall": round(scores.recall, 3),
            "f1": round(scores.f1, 3),
            "severity_agreement": round(self.severity_agreement, 3),
            "error": self.error,
        }


@dataclass
class CalibrationReport:
    papers: list[PaperReport] = field(default_factory=list)
    overall: Scores = field(default_factory=Scores)
    by_severity: dict[str, Scores] = field(default_factory=dict)
    by_category: dict[str, Scores] = field(default_factory=dict)
    by_pass: dict[str, Scores] = field(default_factory=dict)
    severity_agreement: float = 0.0
    settings: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "settings": self.settings,
            "overall": self.overall.as_dict(),
            "severity_agreement": round(self.severity_agreement, 3),
            "by_severity": {k: v.as_dict() for k, v in sorted(self.by_severity.items())},
            "by_category": {k: v.as_dict() for k, v in sorted(self.by_category.items())},
            "by_pass": {k: v.as_dict() for k, v in sorted(self.by_pass.items())},
            "papers": [p.row() for p in self.papers],
            "failed_papers": [{"paper": p.paper, "error": p.error} for p in self.papers if p.error],
            "missed_findings": [
                {"paper": p.paper, **f.model_dump(mode="json")}
                for p in self.papers
                if not p.error
                for f in p.result.missed
            ],
            "spurious_findings": [
                {"paper": p.paper, **f.model_dump(mode="json")}
                for p in self.papers
                if not p.error
                for f in p.result.spurious
            ],
        }


def aggregate(papers: list[PaperReport], settings: dict[str, Any]) -> CalibrationReport:
    """Overall and per-dimension scores across every calibrated paper.

    A paper whose run failed is excluded from the scores: counting its findings as
    misses would silently depress recall for a reason that has nothing to do with
    the model's judgement.
    """
    report = CalibrationReport(papers=papers, settings=settings)
    papers = [p for p in papers if not p.error]
    by_severity: dict[str, Scores] = defaultdict(Scores)
    by_category: dict[str, Scores] = defaultdict(Scores)
    by_pass: dict[str, Scores] = defaultdict(Scores)
    agreed = 0
    matched_total = 0

    for paper in papers:
        for match in paper.result.matches:
            report.overall.true_positives += 1
            by_severity[match.truth.severity.value].true_positives += 1
            by_category[_category(match.truth)].true_positives += 1
            by_pass[_pass(match.predicted)].true_positives += 1
            matched_total += 1
            agreed += 1 if match.severity_agrees else 0
        for finding in paper.result.missed:
            report.overall.false_negatives += 1
            by_severity[finding.severity.value].false_negatives += 1
            by_category[_category(finding)].false_negatives += 1
        for finding in paper.result.spurious:
            report.overall.false_positives += 1
            by_severity[finding.severity.value].false_positives += 1
            by_category[_category(finding)].false_positives += 1
            by_pass[_pass(finding)].false_positives += 1

    report.by_severity = dict(by_severity)
    report.by_category = dict(by_category)
    report.by_pass = dict(by_pass)
    report.severity_agreement = agreed / matched_total if matched_total else 0.0
    return report


def _category(finding: Finding) -> str:
    return (finding.category or "uncategorised").lower()


def _pass(finding: Finding) -> str:
    return finding.source_pass or "unknown"


def write_csv(path: Path, report: CalibrationReport) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAPER_COLUMNS)
        writer.writeheader()
        for paper in report.papers:
            writer.writerow(paper.row())


def render_markdown(report: CalibrationReport) -> str:
    settings = report.settings
    lines = [
        "# Calibration report",
        "",
        f"- Papers: {len(report.papers)}",
        f"- Match threshold: {settings.get('threshold')}",
        f"- Model: {settings.get('model')} ({settings.get('quantization')}) "
        f"via {settings.get('provider')}",
        f"- Prompt version: {settings.get('prompt_version')}, seed {settings.get('seed')}, "
        f"repeats {settings.get('repeats')}",
        "",
        "## Overall agreement",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Precision | {report.overall.precision:.3f} |",
        f"| Recall | {report.overall.recall:.3f} |",
        f"| F1 | {report.overall.f1:.3f} |",
        f"| Severity agreement on matched findings | {report.severity_agreement:.3f} |",
        f"| Matched / missed / spurious | {report.overall.true_positives} / "
        f"{report.overall.false_negatives} / {report.overall.false_positives} |",
        "",
        "## Per paper",
        "",
        "| Paper | Human | Model | Matched | Missed | Spurious | P | R | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for paper in report.papers:
        row = paper.row()
        if paper.error:
            lines.append(
                f"| {row['paper']} | {row['truth_findings']} | - | - | - | - | - | - | - |"
            )
            continue
        lines.append(
            f"| {row['paper']} | {row['truth_findings']} | {row['model_findings']} | "
            f"{row['matched']} | {row['missed']} | {row['spurious']} | "
            f"{row['precision']:.2f} | {row['recall']:.2f} | {row['f1']:.2f} |"
        )

    failed = [p for p in report.papers if p.error]
    if failed:
        lines += ["", "### Papers excluded because the run failed", ""]
        lines += [f"- {p.paper}: {p.error}" for p in failed]

    lines += _score_table("Per severity", report.by_severity)
    lines += _score_table("Per category", report.by_category)
    lines += _score_table(
        "Per pass (precision only; human reviews are not pass-labelled)", report.by_pass
    )

    scored = [p for p in report.papers if not p.error]
    missed = [(p.paper, f) for p in scored for f in p.result.missed]
    lines += ["", "## Findings the model missed", ""]
    if missed:
        for paper_name, finding in missed[:60]:
            quote = " ".join(finding.quote.split())[:110]
            lines.append(
                f"- **{finding.severity.value}** [{paper_name}] {finding.description} "
                f'(quote: "{quote}")'
            )
        if len(missed) > 60:
            lines.append(f"- ...and {len(missed) - 60} more (see calibration.json)")
    else:
        lines.append("- None.")

    spurious = [(p.paper, f) for p in scored for f in p.result.spurious]
    lines += ["", "## Findings the model reported that the human review does not have", ""]
    if spurious:
        for paper_name, finding in spurious[:60]:
            lines.append(
                f"- **{finding.severity.value}** [{paper_name}] ({finding.source_pass}/"
                f"{finding.category}) {' '.join(finding.description.split())[:160]}"
            )
        if len(spurious) > 60:
            lines.append(f"- ...and {len(spurious) - 60} more (see calibration.json)")
    else:
        lines.append("- None.")

    lines += [
        "",
        "> Spurious findings are not necessarily wrong: a human review is rarely exhaustive, "
        "and the pipeline reports mechanical issues most reviewers do not write down. Read the "
        "list before treating precision as an error rate.",
    ]
    return "\n".join(lines) + "\n"


def _score_table(title: str, scores: dict[str, Scores]) -> list[str]:
    lines = [
        "",
        f"## {title}",
        "",
        "| Key | TP | FP | FN | P | R | F1 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    if not scores:
        return [*lines, "| - | 0 | 0 | 0 | 0 | 0 | 0 |"]
    for key, score in sorted(scores.items(), key=lambda kv: -kv[1].true_positives):
        lines.append(
            f"| {key} | {score.true_positives} | {score.false_positives} | "
            f"{score.false_negatives} | {score.precision:.2f} | {score.recall:.2f} | "
            f"{score.f1:.2f} |"
        )
    return lines
