"""Tests for the health probes (module-observability-healthz)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import health as health_mod
from app.config import get_settings
from app.health import OK, ComponentHealth


def _make_client(
    monkeypatch, tmp_path: Path, *, kits_exist: bool
) -> TestClient:
    kits = tmp_path / "kits"
    if kits_exist:
        kits.mkdir()
    env = {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(kits),
        "WEBUI_DIST": "/nonexistent",
    }
    for key, value in env.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _no_network_keycloak(monkeypatch) -> Iterator[None]:
    """Default the optional Keycloak check to ok (no real network call)."""

    def _ok(_settings) -> ComponentHealth:
        return ComponentHealth(
            name="identity-provider",
            kind="api",
            required=False,
            status=OK,
            reason_code="ok",
            latency_ms=1,
        )

    monkeypatch.setattr(health_mod, "_check_keycloak", _ok)
    yield


def test_livez_is_ok_without_dependencies(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    resp = client.get("/livez")
    assert resp.status_code == 200
    body = resp.json()
    assert body["probe"] == "livez"
    assert body["status"] == "ok"
    assert body["components"] == []
    get_settings.cache_clear()


def test_livez_public_no_auth(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    # No Authorization header — probes must be exempt from auth.
    assert client.get("/livez").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/healthz").status_code == 200
    get_settings.cache_clear()


def test_readyz_ok_when_catalog_present(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    resp = client.get("/readyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["components"][0]["name"] == "kit-catalog"
    assert body["components"][0]["required"] is True
    get_settings.cache_clear()


def test_readyz_503_when_catalog_missing(monkeypatch, tmp_path) -> None:
    # Build with the catalog present (wsgidav validates it at mount time),
    # then remove it so the readiness check re-evaluates it as unavailable.
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    (tmp_path / "kits").rmdir()
    resp = client.get("/readyz")
    assert resp.status_code == 503
    assert resp.json()["status"] == "fail"
    get_settings.cache_clear()


def test_healthz_ok_when_all_up(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    get_settings.cache_clear()


def test_healthz_degraded_when_optional_down(monkeypatch, tmp_path) -> None:
    def _fail(_settings) -> ComponentHealth:
        return ComponentHealth(
            name="identity-provider",
            kind="api",
            required=False,
            status="fail",
            reason_code="unreachable",
            latency_ms=1,
        )

    monkeypatch.setattr(health_mod, "_check_keycloak", _fail)
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    resp = client.get("/healthz")
    # Optional dependency down + required ok => degraded, still HTTP 200.
    assert resp.status_code == 200
    assert resp.json()["status"] == "degraded"
    get_settings.cache_clear()


def test_health_payload_has_no_secrets(monkeypatch, tmp_path) -> None:
    client = _make_client(monkeypatch, tmp_path, kits_exist=True)
    text = client.get("/healthz").text
    # No hostnames, URLs, or internal paths leak into the payload.
    assert "auth.example.com" not in text
    assert "https://" not in text
    assert str(tmp_path) not in text
    get_settings.cache_clear()
