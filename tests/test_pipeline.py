"""End-to-end pipeline runs against a scripted model."""

from __future__ import annotations

import csv
import json

import pytest

from fake_llm import FakeLLMClient

from scieval import pipeline
from scieval.schemas import Severity


@pytest.fixture
def fake_client(monkeypatch):
    created: list[FakeLLMClient] = []

    def factory(config, **kwargs):
        client = FakeLLMClient(config)
        created.append(client)
        return client

    monkeypatch.setattr(pipeline, "LLMClient", factory)
    return created


@pytest.fixture
def run(paper_pdf, config, fake_client, tmp_path):
    config.output_dir = tmp_path / "out"
    config.search.reference_provider = "none"
    config.search.web_provider = "none"
    return pipeline.run_review(paper_pdf, config, repeats=1)


def test_run_writes_every_output_file(run):
    expected = {
        "pass0.json", "pass1.json", "pass2.json", "pass3.json", "pass4.json",
        "findings.csv", "findings.json", "synthesis.md", "run.json", "extraction.json",
    }
    assert expected <= {p.name for p in run.run_dir.iterdir()}


def test_findings_are_merged_across_passes(run):
    passes = {f.source_pass for f in run.findings}
    assert {"pass1", "pass2", "pass3"} <= passes
    critical = [f for f in run.findings if f.severity is Severity.critical]
    assert critical and "31.4%" in critical[0].quote
    # Findings are sorted with critical first.
    assert run.findings[0].severity is Severity.critical


def test_provenance_records_model_seed_and_prompts(run):
    data = json.loads((run.run_dir / "run.json").read_text())
    assert data["model"] == "fake-model"
    assert data["quantization"] == "Q4_K_M"
    assert data["seed"] == 42
    assert data["temperature"] == 0.0
    assert data["prompt_version"] == "1.0.0"
    assert data["prompt_hashes"]["system.md"]
    assert data["passes_run"] == ["pass0", "pass1", "pass2", "pass3", "pass4", "synthesis"]
    assert data["total_usage"]["total_tokens"] > 0
    assert data["paper_sha256"]


def test_runs_jsonl_gets_one_line_per_run(run):
    lines = (run.run_dir.parent.parent / "runs.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["run_id"] == run.provenance.run_id


def test_findings_csv_matches_the_findings(run):
    rows = list(csv.DictReader((run.run_dir / "findings.csv").open()))
    assert len(rows) == len(run.findings)
    assert rows[0]["severity"] == "critical"
    assert rows[0]["stability"] == "single_run"


def test_pass0_inventory_drives_the_language_used_for_spellcheck(run):
    assert json.loads((run.run_dir / "pass0.json").read_text())["language"] == "en-GB"


def test_pass1_runs_once_per_section(run, fake_client):
    schema_names = [
        (c["response_format"] or {}).get("json_schema", {}).get("name")
        for c in fake_client[0].calls
    ]
    assert schema_names.count("Pass1Output") >= 5
    assert schema_names.count("Pass2Output") == 1
    assert schema_names.count("Pass0Output") == 1


def test_repeats_mark_stability(paper_pdf, config, fake_client, tmp_path):
    config.output_dir = tmp_path / "out-repeats"
    config.search.reference_provider = "none"
    result = pipeline.run_review(paper_pdf, config, repeats=2)
    stabilities = {f.stability.value for f in result.findings if f.source_pass in {"pass1", "pass2"}}
    # The scripted model is deterministic, so every repeated finding is stable.
    assert stabilities == {"stable"}
    assert json.loads((result.run_dir / "run.json").read_text())["repeats"] == 2
    assert "runs" in json.loads((result.run_dir / "pass2.json").read_text())


def test_only_flag_limits_the_passes(paper_pdf, config, fake_client, tmp_path):
    config.output_dir = tmp_path / "out-only"
    result = pipeline.run_review(paper_pdf, config, only=("pass0", "pass1"))
    assert result.provenance.passes_run == ["pass0", "pass1"]
    assert not (result.run_dir / "pass3.json").exists()
    # With no synthesis call, the deterministic fallback report is written instead.
    assert "## 2. Findings" in (result.run_dir / "synthesis.md").read_text()


def test_no_search_tool_marks_references_unverified(paper_pdf, config, fake_client, tmp_path):
    config.output_dir = tmp_path / "out-nosearch"
    config.search.reference_provider = "none"
    config.search.web_provider = "none"
    result = pipeline.run_review(paper_pdf, config, only=("pass0", "pass3", "pass4"))

    pass3 = json.loads((result.run_dir / "pass3.json").read_text())
    assert pass3["search_tool_available"] is False
    assert {r["status"] for r in pass3["references"]} == {"could_not_verify"}
    assert all(r["notes"].startswith("no_search_tool") for r in pass3["references"])
    assert any("no_search_tool" in limitation for limitation in pass3["limitations"])
    # Citing sentences are still carried through so a human can check quickly.
    assert any(r["citing_sentences"] for r in pass3["references"])

    pass4 = json.loads((result.run_dir / "pass4.json").read_text())
    assert pass4["search_tool_available"] is False
    assert {c["verdict"] for c in pass4["fact_checks"]} == {"could_not_verify"}
    assert pass4["fact_checks"][0]["source_url"] == ""


def test_reference_lookup_results_reach_pass3(paper_pdf, config, fake_client, tmp_path, monkeypatch):
    from scieval.search.base import ReferenceRecord

    class StubLookup:
        name = "stub"
        available = True

        def lookup(self, *, raw, doi=None, title=None, year=None):
            return ReferenceRecord(
                found=True, url="https://doi.org/10.1000/found", title=title or "",
                year=year or "", source="stub",
            )

    monkeypatch.setattr(pipeline, "build_reference_lookup", lambda cfg: StubLookup())
    config.output_dir = tmp_path / "out-lookup"
    result = pipeline.run_review(paper_pdf, config, only=("pass0", "pass3"))

    pass3 = json.loads((result.run_dir / "pass3.json").read_text())
    assert pass3["search_tool_available"] is True
    assert len(pass3["references"]) == 4
    # The URL comes from the lookup, never from the model.
    assert {r["found_at"] for r in pass3["references"] if r["status"] == "verified"} == {
        "https://doi.org/10.1000/found"
    }
    assert pass3["missing_citations"]


def test_latest_pointer_tracks_the_newest_run(run):
    pointer = (run.run_dir.parent / "latest.txt").read_text().strip()
    assert pointer == run.run_dir.name
