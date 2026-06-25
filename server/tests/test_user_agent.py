"""
Tests for client identification: the registry and the User-Agent gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.media_types import VENDOR_MEDIA_TYPE
from app.storage import client_registry
from app.user_agent import UserAgentMiddleware

BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
CUSTOM_UA = "my-coding-agent/1.2"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_register_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "clients.json"
    first = client_registry.register(path, CUSTOM_UA, label="agent")
    assert client_registry.is_registered(path, CUSTOM_UA)
    # Re-registering updates rather than duplicating.
    again = client_registry.register(path, CUSTOM_UA, label="renamed")
    assert again["id"] == first["id"]
    assert len(client_registry.load_clients(path)) == 1
    assert client_registry.load_clients(path)[0]["label"] == "renamed"


def test_registry_unregister(tmp_path: Path) -> None:
    path = tmp_path / "clients.json"
    record = client_registry.register(path, CUSTOM_UA)
    client_registry.unregister(path, record["id"])
    assert not client_registry.is_registered(path, CUSTOM_UA)
    # Idempotent: unregistering again is a no-op.
    client_registry.unregister(path, record["id"])


def test_registry_rejects_empty_ua(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        client_registry.register(tmp_path / "clients.json", "   ")


def test_registry_missing_file_is_empty(tmp_path: Path) -> None:
    assert client_registry.load_clients(tmp_path / "absent.json") == []
    assert not client_registry.is_registered(tmp_path / "absent.json", "x")


# ---------------------------------------------------------------------------
# Middleware gate
# ---------------------------------------------------------------------------


@pytest.fixture()
def ua_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    registry = tmp_path / "clients.json"
    monkeypatch.setattr(
        "app.user_agent.get_settings",
        lambda: type(
            "S",
            (),
            {
                "client_registry_path": registry,
                "server_origin": "https://example.com",
            },
        )(),
    )

    app = FastAPI()

    @app.get("/health")
    def health() -> dict:
        return {"ok": True}

    @app.get("/api/kits")
    def kits() -> dict:
        return {"kits": []}

    @app.post("/api/clients")
    def register() -> dict:
        return {"id": "x"}

    @app.get("/kits/mcp")
    def mcp() -> dict:
        return {"mcp": True}

    app.add_middleware(UserAgentMiddleware)
    client = TestClient(app)
    client.registry_path = registry  # type: ignore[attr-defined]
    return client


def test_browser_ua_allowed(ua_client: TestClient) -> None:
    resp = ua_client.get("/api/kits", headers={"User-Agent": BROWSER_UA})
    assert resp.status_code == 200


def test_custom_ua_unregistered_is_403(ua_client: TestClient) -> None:
    resp = ua_client.get("/api/kits", headers={"User-Agent": CUSTOM_UA})
    assert resp.status_code == 403
    assert "/api/clients" in resp.json()["detail"]


def test_custom_ua_registered_allowed(ua_client: TestClient) -> None:
    client_registry.register(ua_client.registry_path, CUSTOM_UA)
    resp = ua_client.get("/api/kits", headers={"User-Agent": CUSTOM_UA})
    assert resp.status_code == 200


def test_health_exempt_from_ua_gate(ua_client: TestClient) -> None:
    resp = ua_client.get("/health", headers={"User-Agent": CUSTOM_UA})
    assert resp.status_code == 200


def test_mcp_endpoint_exempt_from_ua_gate(ua_client: TestClient) -> None:
    # The gate covers only the REST API; the MCP mount is never gated.
    resp = ua_client.get("/kits/mcp", headers={"User-Agent": CUSTOM_UA})
    assert resp.status_code == 200


def test_registration_route_exempt_from_ua_gate(
    ua_client: TestClient,
) -> None:
    # A brand-new custom client can self-register without being known yet.
    resp = ua_client.post(
        "/api/clients", headers={"User-Agent": CUSTOM_UA}
    )
    assert resp.status_code == 200


def test_clients_router_register_and_gate_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The real clients router + gate together: register via the API, then
    # the previously-refused User-Agent gets through.
    registry = tmp_path / "clients.json"
    fake = type(
        "S",
        (),
        {
            "client_registry_path": registry,
            "server_origin": "https://example.com",
        },
    )()
    monkeypatch.setattr("app.user_agent.get_settings", lambda: fake)
    monkeypatch.setattr("app.routers.clients.get_settings", lambda: fake)

    from app.routers import clients as clients_router

    app = FastAPI()
    app.include_router(clients_router.router)

    @app.get("/api/kits")
    def kits() -> dict:
        return {"kits": []}

    app.add_middleware(UserAgentMiddleware)
    http = TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})

    # Before registration: refused.
    assert (
        http.get("/api/kits", headers={"User-Agent": CUSTOM_UA}).status_code
        == 403
    )
    # Register (the POST route is gate-exempt).
    reg = http.post(
        "/api/clients",
        headers={"User-Agent": CUSTOM_UA},
        json={"user_agent": CUSTOM_UA, "label": "agent"},
    )
    assert reg.status_code == 201
    # After registration: allowed.
    assert (
        http.get("/api/kits", headers={"User-Agent": CUSTOM_UA}).status_code
        == 200
    )
