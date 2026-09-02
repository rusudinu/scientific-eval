"""The local web UI: upload, progress streaming, stored runs, file downloads."""

from __future__ import annotations

import json

import pytest
from fake_llm import FakeLLMClient

from scieval import pipeline
from scieval.web import create_app
from scieval.web.jobs import JobRegistry, safe_filename

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture
def client(config, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "LLMClient", lambda cfg, **kw: FakeLLMClient(cfg))
    config.output_dir = tmp_path / "out"
    config.search.reference_provider = "none"
    config.search.web_provider = "none"
    app = create_app(config, upload_dir=tmp_path / "uploads")
    with TestClient(app) as test_client:
        yield test_client


def _wait_for(client, job_id, timeout=60.0):
    """Read the SSE stream to completion and return the finished job."""
    with client.stream("GET", f"/api/runs/{job_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        event = None
        payloads = []
        for line in response.iter_lines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                payloads.append((event, json.loads(line[6:])))
                if event == "finished":
                    return payloads
    raise AssertionError("stream ended without a finished event")


def test_the_page_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Drop a PDF here" in response.text


def test_config_endpoint_describes_the_server(client):
    data = client.get("/api/config").json()
    assert data["provider"] == "lmstudio"
    assert "pass0" in data["passes"]
    assert data["seed"] == 42


def test_a_non_pdf_upload_is_refused(client, tmp_path):
    fake = tmp_path / "notes.pdf"
    fake.write_text("this is not a pdf")
    response = client.post("/api/runs", files={"file": ("notes.pdf", fake.read_bytes())})
    assert response.status_code == 400
    assert "not a PDF" in response.json()["detail"]


def test_upload_runs_the_pipeline_and_streams_progress(client, paper_pdf):
    response = client.post(
        "/api/runs",
        files={"file": ("dropped.pdf", paper_pdf.read_bytes(), "application/pdf")},
        data={"model": "fake-model", "repeats": "1", "passes": "pass0,pass1"},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    payloads = _wait_for(client, job_id)
    messages = [p["message"] for event, p in payloads if event == "progress"]
    assert "started" in messages
    assert any("pass1" in m for m in messages)

    finished = payloads[-1][1]
    assert finished["status"] == "done"
    result = finished["result"]
    assert result["run_id"]
    assert result["provenance"]["model"] == "fake-model"
    assert result["provenance"]["quantization"] == "Q4_K_M"
    assert result["counts"]["total"] == len(result["findings"])
    assert result["report"]


def test_a_failing_run_is_reported_not_swallowed(client, tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise RuntimeError("the model server went away")

    monkeypatch.setattr("scieval.web.app.run_review", explode)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\ntrailer\n")
    job_id = client.post(
        "/api/runs", files={"file": ("x.pdf", pdf.read_bytes(), "application/pdf")}
    ).json()["job_id"]

    finished = _wait_for(client, job_id)[-1][1]
    assert finished["status"] == "failed"
    assert "the model server went away" in finished["error"]


def test_unknown_job_is_404(client):
    assert client.get("/api/runs/nope").status_code == 404
    assert client.get("/api/runs/nope/events").status_code == 404


def test_history_lists_the_run_and_serves_its_files(client, paper_pdf):
    job_id = client.post(
        "/api/runs",
        files={"file": ("dropped.pdf", paper_pdf.read_bytes(), "application/pdf")},
        data={"passes": "pass0,pass1"},
    ).json()["job_id"]
    _wait_for(client, job_id)

    runs = client.get("/api/history").json()["runs"]
    assert runs, "the finished run is missing from the history"
    row = runs[0]
    assert row["paper"] == "dropped.pdf"
    assert row["available"] is True
    assert row["model"] == "fake-model"

    stored = client.get(f"/api/history/{row['paper_slug']}/{row['run_id']}").json()
    assert stored["counts"]["total"] >= 0
    assert stored["report"]
    assert "findings.csv" in stored["files"]

    csv = client.get(f"/api/history/{row['paper_slug']}/{row['run_id']}/files/findings.csv")
    assert csv.status_code == 200
    assert csv.text.splitlines()[0].startswith("pass,severity,category")


def test_stored_run_endpoints_reject_unknown_and_traversal(client):
    assert client.get("/api/history/nope/nope").status_code == 404
    escape = client.get("/api/history/nope/nope/files/..%2F..%2F..%2Fetc%2Fpasswd")
    assert escape.status_code == 404


def test_history_is_empty_before_any_run(client):
    assert client.get("/api/history").json()["runs"] == []


# --- job registry ---------------------------------------------------------------


def test_uploaded_filenames_are_made_safe():
    assert safe_filename("../../etc/passwd") == "passwd.pdf"
    assert safe_filename("My Paper (v2).pdf") == "My Paper v2.pdf"
    assert safe_filename("") == "paper.pdf"
    assert safe_filename("report.PDF") == "report.PDF"


def test_the_registry_records_failures_without_raising():
    registry = JobRegistry()
    try:
        job = registry.submit("x.pdf", lambda emit: (_ for _ in ()).throw(ValueError("boom")))
        for _ in range(200):
            if job.finished:
                break
            import time

            time.sleep(0.02)
        assert job.status == "failed"
        assert "boom" in job.error
    finally:
        registry.shutdown()


def test_the_registry_evicts_old_jobs():
    registry = JobRegistry(max_jobs=2)
    try:
        first = registry.submit("a.pdf", lambda emit: None)
        registry.submit("b.pdf", lambda emit: None)
        registry.submit("c.pdf", lambda emit: None)
        assert registry.get(first.id) is None
    finally:
        registry.shutdown()
