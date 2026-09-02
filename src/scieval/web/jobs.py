"""In-process job registry for the web UI.

A review takes minutes, so the HTTP request that starts one must not wait for it.
Jobs run on a single worker thread (LM Studio serialises requests anyway) and
publish progress lines that the browser reads over SSE. Events are kept per job
so a reconnecting page can replay from the beginning rather than miss the run.
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

Runner = Callable[[Callable[[str], None]], Any]


@dataclass
class Job:
    """One queued or running review."""

    id: str
    paper_name: str
    status: str = "queued"  # queued | running | done | failed
    events: list[str] = field(default_factory=list)
    result: dict[str, Any] | None = None
    error: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_event(self, message: str) -> None:
        with self._lock:
            self.events.append(message)

    def events_since(self, index: int) -> list[str]:
        with self._lock:
            return self.events[index:]

    @property
    def finished(self) -> bool:
        return self.status in {"done", "failed"}

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "id": self.id,
                "paper_name": self.paper_name,
                "status": self.status,
                "created_at": self.created_at,
                "event_count": len(self.events),
                "result": self.result,
                "error": self.error,
            }


class JobRegistry:
    """Runs one review at a time and keeps the recent ones addressable."""

    def __init__(self, max_jobs: int = 50) -> None:
        self._jobs: dict[str, Job] = {}
        self._order: list[str] = []
        self._max_jobs = max_jobs
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scieval-run")

    def submit(self, paper_name: str, runner: Runner) -> Job:
        job = Job(id=uuid4().hex[:12], paper_name=paper_name)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            while len(self._order) > self._max_jobs:
                self._jobs.pop(self._order.pop(0), None)
        job.add_event("queued")
        self._executor.submit(self._run, job, runner)
        return job

    def _run(self, job: Job, runner: Runner) -> None:
        job.status = "running"
        job.add_event("started")
        try:
            job.result = runner(job.add_event)
            job.status = "done"
            job.add_event("done")
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.add_event(f"failed: {job.error}")
            traceback.print_exc()

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def safe_filename(name: str) -> str:
    """Keep an uploaded filename usable as a path component."""
    cleaned = Path(name or "paper.pdf").name
    cleaned = "".join(c for c in cleaned if c.isalnum() or c in "._- ").strip()
    if not cleaned.lower().endswith(".pdf"):
        cleaned = f"{cleaned or 'paper'}.pdf"
    return cleaned or "paper.pdf"
