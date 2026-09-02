"""FastAPI app behind `scieval serve`: drop a PDF, watch it run, read the report.

Note: this module deliberately does not use `from __future__ import annotations`.
The routes are defined inside `create_app`, and postponed annotations reach
FastAPI as ForwardRefs it cannot resolve against that local scope, which silently
turns an uploaded file into a missing query parameter.
"""

import asyncio
import json
from pathlib import Path
from typing import Annotated, Any

from ..config import Config
from ..llm.client import LLMClient, LLMError
from ..pipeline import ALL_PASSES, run_review
from ..report import slugify
from .jobs import JobRegistry, safe_filename

STATIC_DIR = Path(__file__).resolve().parent / "static"
POLL_SECONDS = 0.3


class MissingDependency(RuntimeError):
    """Raised when the web extras are not installed."""


def create_app(config: Config, *, upload_dir: Path | None = None):
    try:
        from fastapi import FastAPI, File, Form, HTTPException, UploadFile
        from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
    except ImportError as exc:  # pragma: no cover - exercised by the CLI hint
        raise MissingDependency(
            "the web UI needs fastapi and uvicorn: run `uv sync` in the project, "
            "or `uv pip install fastapi uvicorn python-multipart`"
        ) from exc

    uploads = upload_dir or (config.output_dir / "_uploads")
    uploads.mkdir(parents=True, exist_ok=True)
    registry = JobRegistry()

    app = FastAPI(title="scientific-eval", docs_url=None, redoc_url=None)
    app.state.registry = registry
    app.state.config = config

    @app.on_event("shutdown")
    def _shutdown() -> None:
        registry.shutdown()

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/config")
    def read_config() -> dict[str, Any]:
        return {
            "provider": config.provider_name,
            "base_url": config.provider.base_url,
            "default_model": config.model_for("pass0"),
            "seed": config.seed,
            "temperature": config.temperature,
            "output_dir": str(config.output_dir),
            "reference_provider": config.search.reference_provider,
            "web_search_provider": config.search.web_provider,
            "passes": list(ALL_PASSES),
        }

    @app.get("/api/models")
    def models() -> dict[str, Any]:
        try:
            client = LLMClient(config)
            listed = client.list_models()
        except (LLMError, Exception) as exc:
            return {"models": [], "error": str(exc)}
        return {
            "models": [
                {
                    "id": entry.get("id", ""),
                    "quantization": client.native_model_info(str(entry.get("id", ""))).get(
                        "quantization"
                    ),
                }
                for entry in listed
            ],
            "error": "",
        }

    @app.post("/api/runs")
    async def start_run(
        # Declared explicitly: a bare `UploadFile` annotation is read as a query
        # parameter by current FastAPI when other form fields are present.
        file: Annotated[UploadFile, File()],
        model: Annotated[str, Form()] = "",
        repeats: Annotated[int, Form()] = 1,
        passes: Annotated[str, Form()] = "",
    ) -> dict[str, Any]:
        name = safe_filename(file.filename or "paper.pdf")
        content = await file.read()
        if not content.startswith(b"%PDF"):
            raise HTTPException(status_code=400, detail=f"{name} is not a PDF file")
        target = uploads / name
        target.write_bytes(content)

        selected = tuple(p for p in passes.split(",") if p in ALL_PASSES) or None
        run_config = config
        if model:
            run_config = _with_model(config, model)

        def runner(emit) -> dict[str, Any]:
            result = run_review(
                target, run_config, repeats=max(1, min(repeats, 5)), only=selected, emit=emit
            )
            return {
                "run_id": result.provenance.run_id,
                "paper": result.paper.name,
                "run_dir": str(result.run_dir),
                "counts": _counts(result.findings),
                "findings": [f.model_dump(mode="json") for f in result.findings],
                "provenance": result.provenance.as_dict(),
                "report": result.report,
            }

        job = registry.submit(name, runner)
        return {"job_id": job.id}

    @app.get("/api/runs/{job_id}")
    def read_job(job_id: str) -> dict[str, Any]:
        job = registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return job.as_dict()

    @app.get("/api/runs/{job_id}/events")
    async def stream_events(job_id: str):
        job = registry.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")

        async def generate():
            sent = 0
            while True:
                for message in job.events_since(sent):
                    sent += 1
                    yield _sse("progress", {"message": message})
                if job.finished and sent >= len(job.events):
                    yield _sse("finished", job.as_dict())
                    return
                await asyncio.sleep(POLL_SECONDS)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/history")
    def history(limit: int = 50) -> dict[str, Any]:
        return {"runs": _read_history(config.output_dir, limit)}

    @app.get("/api/history/{paper}/{run_id}")
    def stored_run(paper: str, run_id: str) -> dict[str, Any]:
        run_dir = _run_dir(config.output_dir, paper, run_id)
        findings_file = run_dir / "findings.json"
        report_file = run_dir / "synthesis.md"
        run_file = run_dir / "run.json"
        if not findings_file.is_file():
            raise HTTPException(status_code=404, detail="no findings stored for that run")
        findings = json.loads(findings_file.read_text(encoding="utf-8"))
        return {
            "run_id": run_id,
            "paper": paper,
            "run_dir": str(run_dir),
            "counts": findings.get("counts", {}),
            "findings": findings.get("findings", []),
            "report": report_file.read_text(encoding="utf-8") if report_file.is_file() else "",
            "provenance": json.loads(run_file.read_text(encoding="utf-8"))
            if run_file.is_file()
            else {},
            "files": sorted(p.name for p in run_dir.glob("*") if p.is_file()),
        }

    @app.get("/api/history/{paper}/{run_id}/files/{name}")
    def stored_file(paper: str, run_id: str, name: str):
        run_dir = _run_dir(config.output_dir, paper, run_id)
        target = (run_dir / Path(name).name).resolve()
        if not target.is_file() or run_dir.resolve() not in target.parents:
            raise HTTPException(status_code=404, detail="no such file in that run")
        return FileResponse(target, filename=f"{paper}-{run_id}-{target.name}")

    return app


def _with_model(config: Config, model: str) -> Config:
    """A shallow copy with the model overridden, so one run cannot mutate the server."""
    import copy

    clone = copy.copy(config)
    clone.models = dict(config.models, default=model)
    return clone


def _counts(findings) -> dict[str, int]:
    counts = {"critical": 0, "major": 0, "minor": 0}
    for finding in findings:
        counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
    counts["total"] = len(findings)
    return counts


def _run_dir(output_dir: Path, paper: str, run_id: str) -> Path:
    """Resolve a stored run, refusing anything that escapes the output directory."""
    root = output_dir.resolve()
    candidate = (root / Path(paper).name / Path(run_id).name).resolve()
    if root not in candidate.parents and candidate.parent != root:
        raise ValueError("path outside the output directory")
    if not candidate.is_dir():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="unknown run")
    return candidate


def _read_history(output_dir: Path, limit: int) -> list[dict[str, Any]]:
    """Recent runs, newest first, taken from the run log the pipeline appends to."""
    log = output_dir / "runs.jsonl"
    if not log.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in log.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        paper = row.get("paper", "")
        row["paper_slug"] = slugify(Path(paper).stem)
        run_dir = output_dir / row["paper_slug"] / str(row.get("run_id", ""))
        row["available"] = (run_dir / "findings.json").is_file()
        rows.append(row)
    rows.reverse()
    return rows[:limit]


def _sse(event: str, payload: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
