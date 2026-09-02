"""Calibration: ground-truth loading, finding matching, agreement metrics."""

from __future__ import annotations

import json

import pytest

from scieval.calibrate import (
    GroundTruthError,
    TEMPLATE,
    aggregate,
    find_pairs,
    load,
    match_findings,
    render_markdown,
    write_csv,
)
from scieval.calibrate.metrics import PaperReport
from scieval.schemas import Finding, Severity


def _finding(quote, description="", severity=Severity.major, category="numbers",
             location="4 Results", source_pass="pass2") -> Finding:
    return Finding(
        severity=severity, category=category, location=location, quote=quote,
        description=description, source_pass=source_pass,
    )


def _write_review(folder, stem, findings) -> None:
    (folder / f"{stem}.pdf").write_bytes(b"%PDF-1.4\n")
    (folder / f"{stem}.review.json").write_text(
        json.dumps({"paper": f"{stem}.pdf", "findings": findings}), encoding="utf-8"
    )


def test_find_pairs_only_returns_reviewed_papers(tmp_path):
    _write_review(tmp_path, "reviewed", [])
    (tmp_path / "unreviewed.pdf").write_bytes(b"%PDF-1.4\n")
    pairs = find_pairs(tmp_path)
    assert [p[0].name for p in pairs] == ["reviewed.pdf"]


def test_load_accepts_a_bare_list(tmp_path):
    (tmp_path / "p.pdf").write_bytes(b"%PDF")
    review = tmp_path / "p.review.json"
    review.write_text(json.dumps([
        {"severity": "minor", "category": "spelling", "quote": "teh", "description": "typo"}
    ]))
    truth = load(tmp_path / "p.pdf", review)
    assert len(truth.findings) == 1
    assert truth.findings[0].severity is Severity.minor


def test_load_rejects_an_invalid_severity(tmp_path):
    (tmp_path / "p.pdf").write_bytes(b"%PDF")
    review = tmp_path / "p.review.json"
    review.write_text(json.dumps({"findings": [{"severity": "catastrophic", "quote": "x"}]}))
    with pytest.raises(GroundTruthError, match="severity must be one of"):
        load(tmp_path / "p.pdf", review)


def test_load_rejects_invalid_json(tmp_path):
    (tmp_path / "p.pdf").write_bytes(b"%PDF")
    review = tmp_path / "p.review.json"
    review.write_text("{not json")
    with pytest.raises(GroundTruthError, match="invalid JSON"):
        load(tmp_path / "p.pdf", review)


def test_template_is_loadable(tmp_path):
    (tmp_path / "example.pdf").write_bytes(b"%PDF")
    review = tmp_path / "example.review.json"
    review.write_text(json.dumps(TEMPLATE))
    assert len(load(tmp_path / "example.pdf", review).findings) == 2


def test_matching_pairs_the_same_issue_despite_wording():
    truth = [_finding(
        "accuracy of 94.2% on the held-out set",
        "The abstract says 94.2% but Table 3 says 91.7%.",
    )]
    predicted = [_finding(
        "accuracy of 94.2% on the held-out set",
        "Abstract reports 94.2%, Table 3 reports 91.7% for the same run.",
    )]
    result = match_findings(truth, predicted)
    assert len(result.matches) == 1
    assert result.matches[0].severity_agrees is True
    assert not result.missed and not result.spurious


def test_unrelated_findings_do_not_match():
    truth = [_finding("accuracy of 94.2%", "Numbers disagree.")]
    predicted = [_finding("we optimise the cache", "British spelling used here.",
                          category="language")]
    result = match_findings(truth, predicted)
    assert not result.matches
    assert len(result.missed) == 1
    assert len(result.spurious) == 1


def test_matching_is_one_to_one():
    truth = [_finding("accuracy of 94.2% on the held-out set", "Numbers disagree.")]
    predicted = [
        _finding("accuracy of 94.2% on the held-out set", "Numbers disagree."),
        _finding("accuracy of 94.2% on the held-out set", "Numbers disagree."),
    ]
    result = match_findings(truth, predicted)
    assert len(result.matches) == 1
    assert len(result.spurious) == 1


def test_severity_disagreement_is_recorded():
    truth = [_finding("same quote text here", "Same issue.", severity=Severity.critical)]
    predicted = [_finding("same quote text here", "Same issue.", severity=Severity.minor)]
    result = match_findings(truth, predicted)
    assert result.matches[0].severity_agrees is False


def test_metrics_add_up():
    truth = [
        _finding("quote one exactly here", "First issue."),
        _finding("quote two exactly here", "Second issue."),
    ]
    predicted = [
        _finding("quote one exactly here", "First issue."),
        _finding("completely different text", "Unrelated.", category="grammar"),
    ]
    report = aggregate(
        [PaperReport(
            paper="p.pdf", run_id="r1", result=match_findings(truth, predicted),
            truth_count=2, predicted_count=2,
        )],
        {"threshold": 70.0},
    )
    assert report.overall.true_positives == 1
    assert report.overall.false_negatives == 1
    assert report.overall.false_positives == 1
    assert report.overall.precision == pytest.approx(0.5)
    assert report.overall.recall == pytest.approx(0.5)
    assert report.overall.f1 == pytest.approx(0.5)
    assert report.severity_agreement == pytest.approx(1.0)


def test_perfect_and_empty_scores_do_not_divide_by_zero():
    report = aggregate([], {"threshold": 70.0})
    assert report.overall.precision == 0.0
    assert report.overall.f1 == 0.0


def test_report_files_render(tmp_path):
    truth = [_finding("quote one exactly here", "First issue.")]
    predicted = [_finding("quote one exactly here", "First issue.")]
    report = aggregate(
        [PaperReport(paper="p.pdf", run_id="r1", result=match_findings(truth, predicted),
                     truth_count=1, predicted_count=1)],
        {"threshold": 70.0, "model": "m", "quantization": "Q4", "provider": "lmstudio",
         "prompt_version": "1.0.0", "seed": 42, "repeats": 1},
    )
    markdown = render_markdown(report)
    assert "# Calibration report" in markdown
    assert "Per severity" in markdown
    assert "Q4" in markdown

    csv_path = tmp_path / "calibration.csv"
    write_csv(csv_path, report)
    header = csv_path.read_text().splitlines()[0]
    assert header.startswith("paper,run_id,truth_findings")

    payload = report.as_dict()
    assert payload["overall"]["precision"] == 1.0
    assert payload["papers"][0]["paper"] == "p.pdf"
