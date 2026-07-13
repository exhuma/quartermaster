"""In-memory registry for asynchronous evaluation runs.

An eval run scores the whole corpus (embedding inference per case) and can take
several seconds, so the API starts it as a background job and lets the caller
poll for the report. The store is process-local and disposable — jobs are
ephemeral measurements, not durable state — so a restart simply forgets them.

.. note::
   Being in-memory, the store is not shared across multiple worker processes.
   For a single-process deployment (the default) a poll always reaches the
   worker that owns the job. A multi-worker deployment would need a shared
   backend; out of scope for this first cut.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

STATUSES = ("pending", "running", "completed", "failed")


class EvalJobNotFoundError(LookupError):
    """Raised when an eval job id is unknown."""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class EvalJob:
    """One evaluation run and its lifecycle state."""

    id: str
    params: dict[str, Any]
    status: str = "pending"
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None

    def to_public(self) -> dict[str, Any]:
        """Serialise for the API — report/error only when terminal."""
        out: dict[str, Any] = {
            "job_id": self.id,
            "status": self.status,
            "params": self.params,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }
        if self.status == "completed":
            out["report"] = self.result
        elif self.status == "failed":
            out["error"] = self.error
        return out


class EvalJobStore:
    """Thread-safe registry; the worker thread mutates via mark_* methods."""

    def __init__(self) -> None:
        self._jobs: dict[str, EvalJob] = {}
        self._lock = threading.Lock()

    def create(self, params: dict[str, Any]) -> EvalJob:
        job = EvalJob(id=uuid.uuid4().hex, params=dict(params))
        with self._lock:
            self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> EvalJob:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise EvalJobNotFoundError(job_id)
        return job

    def _set(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                for key, value in fields.items():
                    setattr(job, key, value)

    def mark_running(self, job_id: str) -> None:
        self._set(job_id, status="running")

    def mark_completed(self, job_id: str, result: dict[str, Any]) -> None:
        self._set(job_id, status="completed", result=result, finished_at=_now())

    def mark_failed(self, job_id: str, error: str) -> None:
        self._set(job_id, status="failed", error=error, finished_at=_now())
