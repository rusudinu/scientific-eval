"""CLI surface: commands run, flags are validated, calibration writes its report."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from fake_llm import FakeLLMClient

from scieval import pipeline
from scieval.cli import app

runner = CliRunner()


@pytest.fixture
def fake_client(monkeypatch):
    monkeypatch.setattr(pipeline, "LLMClient", lambda config, **kw: FakeLLMClient(config))


def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "scientific-eval" in result.stdout


def test_config_show_prints_the_effective_settings():
    result = runner.invoke(app, ["config-show"])
    assert result.exit_code == 0
    assert "lmstudio" in result.stdout


def test_extract_needs_no_server(paper_pdf, tmp_path):
    target = tmp_path / "extraction.json"
    result = runner.invoke(app, ["extract", str(paper_pdf), "--json", str(target)])
    assert result.exit_code == 0
    data = json.loads(target.read_text())
    assert data["pages"] >= 1
    assert len(data["references"]) == 4
    assert data["sections"]


def test_extract_rejects_an_unknown_show_value(paper_pdf):
    result = runner.invoke(app, ["extract", str(paper_pdf), "--show", "nope"])
    assert result.exit_code != 0


def test_review_rejects_an_unknown_pass(paper_pdf):
    result = runner.invoke(app, ["review", str(paper_pdf), "--only", "pass9"])
    assert result.exit_code != 0
    assert "unknown pass" in result.output


def test_review_rejects_a_malformed_model_pass(paper_pdf):
    result = runner.invoke(app, ["review", str(paper_pdf), "--model-pass", "pass2"])
    assert result.exit_code != 0


def test_review_runs_and_prints_a_summary(paper_pdf, tmp_path, fake_client):
    result = runner.invoke(
        app, ["review", str(paper_pdf), "--out", str(tmp_path / "out"), "--only", "pass0,pass1"]
    )
    assert result.exit_code == 0, result.output
    assert "findings" in result.output
    assert (tmp_path / "out").exists()


def test_review_reports_a_connection_failure_clearly(paper_pdf, tmp_path, monkeypatch):
    from scieval.llm.client import LLMError

    def explode(config, **kwargs):
        raise LLMError("cannot list models at http://localhost:1234/v1: refused")

    monkeypatch.setattr(pipeline, "LLMClient", explode)
    result = runner.invoke(app, ["review", str(paper_pdf), "--out", str(tmp_path / "o")])
    assert result.exit_code == 1
    assert "Is the server running" in result.output


def test_init_review_writes_a_template(tmp_path):
    paper = tmp_path / "study.pdf"
    paper.write_bytes(b"%PDF")
    result = runner.invoke(app, ["init-review", str(paper)])
    assert result.exit_code == 0
    data = json.loads((tmp_path / "study.review.json").read_text())
    assert data["paper"] == "study.pdf"
    assert data["findings"]

    # Refuses to overwrite an existing review.
    assert runner.invoke(app, ["init-review", str(paper)]).exit_code == 1


def test_calibrate_end_to_end(paper_pdf, tmp_path, fake_client):
    folder = tmp_path / "reviewed"
    folder.mkdir()
    target = folder / "synthetic-paper.pdf"
    target.write_bytes(paper_pdf.read_bytes())
    (folder / "synthetic-paper.review.json").write_text(
        json.dumps(
            {
                "paper": "synthetic-paper.pdf",
                "findings": [
                    {
                        "severity": "critical",
                        "category": "numbers",
                        "location": "Abstract, p. 1",
                        "quote": "a mean latency reduction of 31.4%",
                        "description": "The abstract claims 31.4% but the table supports 27.2%.",
                    },
                    {
                        "severity": "major",
                        "category": "statistics",
                        "location": "4 Results",
                        "quote": "p = 0.048",
                        "description": "No effect size or confidence interval is reported.",
                    },
                ],
            }
        )
    )
    result = runner.invoke(
        app, ["calibrate", str(folder), "--out", str(tmp_path / "out")]
    )
    assert result.exit_code == 0, result.output

    report = json.loads((folder / "calibration.json").read_text())
    assert report["overall"]["true_positives"] == 1     # the 31.4% finding matches
    assert report["overall"]["false_negatives"] == 1    # the statistics finding is missed
    assert report["papers"][0]["paper"] == "synthetic-paper.pdf"
    assert (folder / "calibration.md").exists()
    assert (folder / "calibration.csv").exists()
    assert "overall precision" in result.output


def test_calibrate_without_pairs_fails_clearly(tmp_path):
    result = runner.invoke(app, ["calibrate", str(tmp_path)])
    assert result.exit_code == 2
    assert "no paper/review pairs" in result.output


def test_calibrate_reuse_uses_the_stored_run(paper_pdf, tmp_path, fake_client):
    folder = tmp_path / "reviewed"
    folder.mkdir()
    (folder / "synthetic-paper.pdf").write_bytes(paper_pdf.read_bytes())
    (folder / "synthetic-paper.review.json").write_text(json.dumps({"findings": []}))
    out = tmp_path / "out"

    first = runner.invoke(app, ["calibrate", str(folder), "--out", str(out)])
    assert first.exit_code == 0
    runs_before = (out / "runs.jsonl").read_text().count("\n")

    second = runner.invoke(app, ["calibrate", str(folder), "--out", str(out), "--reuse"])
    assert second.exit_code == 0
    assert (out / "runs.jsonl").read_text().count("\n") == runs_before
