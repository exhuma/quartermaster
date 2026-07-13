"""
Tests for the eval API (``/api/eval/resolution``).

The router is mounted on a bare FastAPI app (no JWT/UA middleware) with the
domain-exception handlers registered, to isolate the endpoint contract: vendor
``Accept`` negotiation, the async job envelope, and the 404 for unknown jobs.
The heavy runner is stubbed and the job executed inline, so no catalog or model
is needed here (the real run path is covered by ``test_eval_runner``).
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.main import _register_exception_handlers
from app.media_types import VENDOR_MEDIA_TYPE
from app.routers import eval as eval_router
from app.services import eval_service

_FAKE_REPORT = {
    "totals": {"cases": 3, "passed": 2, "failed": 1},
    "cases": [],
    "false_exclusion_tally": {},
    "language_contamination": {},
    "engine_drift": [],
    "nondeterministic": [],
}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Run the job inline (no thread) with a stubbed runner for determinism.
    monkeypatch.setattr(eval_service, "_submit", lambda work: work())
    monkeypatch.setattr(
        eval_service,
        "run_resolution_eval",
        lambda which, limit: {
            **_FAKE_REPORT,
            "params": {"cases": which, "limit": limit},
        },
    )
    app = FastAPI()
    app.include_router(eval_router.router)
    _register_exception_handlers(app)
    return TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


def _start(client: TestClient, body: dict[str, Any] | None = None) -> Any:
    return client.post(
        "/api/eval/resolution", json=body if body is not None else {}
    )


def test_start_returns_accepted_and_completes(client: TestClient) -> None:
    resp = _start(client)
    assert resp.status_code == 202
    assert VENDOR_MEDIA_TYPE in resp.headers["content-type"]
    body = resp.json()
    assert body["status"] == "completed"  # inline execution
    assert "job_id" in body
    assert body["report"]["totals"]["cases"] == 3


def test_poll_known_job(client: TestClient) -> None:
    job_id = _start(client).json()["job_id"]
    resp = client.get(f"/api/eval/resolution/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["report"] == {
        **_FAKE_REPORT,
        "params": {"cases": "all", "limit": 0},
    }


def test_params_passed_through(client: TestClient) -> None:
    body = _start(client, {"cases": "curated", "limit": 5}).json()
    assert body["params"] == {"cases": "curated", "limit": 5}
    assert body["report"]["params"] == {"cases": "curated", "limit": 5}


def test_unknown_job_is_404(client: TestClient) -> None:
    resp = client.get("/api/eval/resolution/does-not-exist")
    assert resp.status_code == 404


def test_bare_json_accept_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/eval/resolution",
        json={},
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 406


def test_invalid_cases_rejected(client: TestClient) -> None:
    resp = _start(client, {"cases": "bogus"})
    assert resp.status_code == 422


def test_failed_run_surfaces_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(which: str, limit: int) -> dict[str, Any]:
        raise RuntimeError("catalog unreadable")

    monkeypatch.setattr(eval_service, "run_resolution_eval", _boom)
    body = _start(client).json()
    assert body["status"] == "failed"
    assert "catalog unreadable" in body["error"]
