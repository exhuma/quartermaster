"""Tests for the hardening middleware (module-http-middleware-hardening)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.logging_config import get_correlation_id
from app.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    VersionHeaderMiddleware,
)
from app.rate_limit import enforce_limit_or_429


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/thing")
    async def thing() -> dict:
        # Expose the request-scoped correlation id so the test can assert it
        # matches the echoed response header (proves contextvar propagation).
        return {"cid": get_correlation_id()}

    # Same registration order as create_app (LIFO -> RequestLogging outermost).
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(VersionHeaderMiddleware, version="9.9.9")
    app.add_middleware(RequestLoggingMiddleware)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


def test_security_headers_on_every_response(client: TestClient) -> None:
    resp = client.get("/thing")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert (
        resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    )


def test_security_headers_present_on_404(client: TestClient) -> None:
    resp = client.get("/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Quartermaster-Version"] == "9.9.9"
    assert "X-Correlation-ID" in resp.headers


def test_version_header(client: TestClient) -> None:
    resp = client.get("/thing")
    assert resp.headers["X-Quartermaster-Version"] == "9.9.9"


def test_correlation_id_generated_and_echoed(client: TestClient) -> None:
    resp = client.get("/thing")
    cid = resp.headers["X-Correlation-ID"]
    assert cid
    # The handler saw the same id via the contextvar (shared by all logs).
    assert resp.json()["cid"] == cid


def test_inbound_correlation_id_preserved(client: TestClient) -> None:
    resp = client.get("/thing", headers={"X-Correlation-ID": "abc-123"})
    assert resp.headers["X-Correlation-ID"] == "abc-123"
    assert resp.json()["cid"] == "abc-123"


def test_correlation_id_cleared_between_requests(client: TestClient) -> None:
    client.get("/thing", headers={"X-Correlation-ID": "first"})
    # A second request without the header must not inherit "first".
    resp = client.get("/thing")
    assert resp.headers["X-Correlation-ID"] != "first"


def test_rate_limit_allows_under_limit() -> None:
    for _ in range(3):
        enforce_limit_or_429(
            key="test-under", limit=3, window_seconds=60, scope="t"
        )  # no raise


def test_rate_limit_429_with_rfc6585_headers() -> None:
    from fastapi import HTTPException

    for _ in range(2):
        enforce_limit_or_429(
            key="test-over", limit=2, window_seconds=60, scope="t"
        )
    with pytest.raises(HTTPException) as exc:
        enforce_limit_or_429(
            key="test-over", limit=2, window_seconds=60, scope="t"
        )
    assert exc.value.status_code == 429
    headers = exc.value.headers or {}
    for name in (
        "RateLimit-Limit",
        "RateLimit-Remaining",
        "RateLimit-Reset",
        "Retry-After",
    ):
        assert name in headers
    assert int(headers["Retry-After"]) >= 1
