"""Business logic for catalog-evaluation runs.

Owns the process-local job store and starts each run on a background worker so
the API can return immediately and the caller can poll. The heavy work lives in
``app.eval.runner``; this layer only orchestrates job lifecycle.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from app.eval.jobs import EvalJob, EvalJobStore
from app.eval.runner import run_resolution_eval

VALID_CASE_SETS = ("catalog", "curated", "all")

_store = EvalJobStore()


def _run_in_thread(work: Callable[[], None]) -> None:
    threading.Thread(target=work, daemon=True).start()


# Indirection so tests can execute the job inline (deterministic, no threads).
_submit: Callable[[Callable[[], None]], None] = _run_in_thread


def start_resolution_eval(cases: str = "all", limit: int = 0) -> EvalJob:
    """Create a job and start the run in the background.

    :raises ValueError: if *cases* is not a known set or *limit* is negative.
    """
    if cases not in VALID_CASE_SETS:
        raise ValueError(
            f"unknown case set {cases!r}; expected one of {VALID_CASE_SETS}"
        )
    if limit < 0:
        raise ValueError("limit must be >= 0")

    job = _store.create({"cases": cases, "limit": limit})

    def _work() -> None:
        _store.mark_running(job.id)
        try:
            report = run_resolution_eval(which=cases, limit=limit)
        except Exception as exc:  # noqa: BLE001 - surface as a failed job
            _store.mark_failed(job.id, str(exc))
        else:
            _store.mark_completed(job.id, report)

    _submit(_work)
    return job


def get_resolution_eval(job_id: str) -> EvalJob:
    """Return a job by id.

    :raises EvalJobNotFoundError: if the id is unknown.
    """
    return _store.get(job_id)
