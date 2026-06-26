"""
Tests for the Prometheus ``/metrics`` pull endpoint and its auth posture.

``/metrics`` is authenticated with app-token HTTP Basic by default (Prometheus
cannot run an OIDC flow), and public only when ``QM_METRICS_ALLOW_ANONYMOUS``
is set. It is exempt from the User-Agent gate (it lives outside ``/api``).
"""

from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.storage import app_tokens


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    allow_anonymous: bool,
) -> TestClient:
    kits = tmp_path / "kits"
    kits.mkdir()
    env = {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(kits),
        "WEBUI_DIST": "/nonexistent",
        "APP_TOKENS_PATH": str(tmp_path / "app_tokens.json"),
        "METRICS_PROMETHEUS_ENABLED": "true",
    }
    if allow_anonymous:
        env["METRICS_ALLOW_ANONYMOUS"] = "true"
    for key, value in env.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


def _basic(user: str, token: str) -> str:
    raw = base64.b64encode(f"{user}:{token}".encode()).decode()
    return f"Basic {raw}"


def test_metrics_requires_auth_by_default(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, allow_anonymous=False)
    resp = client.get("/metrics")
    assert resp.status_code == 401


def test_metrics_served_with_app_token(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, allow_anonymous=False)
    # Mint a valid app token bound to a user in the configured store.
    _public, token = app_tokens.mint(
        get_settings().app_tokens_path, "alice", "prometheus"
    )
    resp = client.get(
        "/metrics", headers={"Authorization": _basic("scraper", token)}
    )
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


def test_metrics_rejects_bad_app_token(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, allow_anonymous=False)
    resp = client.get(
        "/metrics", headers={"Authorization": _basic("scraper", "nope")}
    )
    assert resp.status_code == 401


def test_metrics_anonymous_when_allowed(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, allow_anonymous=True)
    # No Authorization header, and no User-Agent registration required.
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]
