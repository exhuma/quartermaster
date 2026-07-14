"""Tests for the /api/integration payload, including auth-less mode.

The integration endpoint feeds the web UI's "how to connect an agent" page.
In auth-less mode it must advertise ``auth_disabled`` and never read the
now-optional Keycloak config (which would be ``None``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.routers import integration


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        auth_disabled=False,
        server_origin="https://instructions.example.com",
        keycloak_issuer="https://auth.example.com/realms/master",
        keycloak_realm="master",
        webui_keycloak_client_id="quartermaster-webui",
        oauth_scopes=["openid", "profile", "email"],
        oauth_metadata_url="https://instructions.example.com/.well-known/x",
        authorization_endpoint="https://auth.example.com/auth",
        token_endpoint="https://auth.example.com/token",
        copilot_auth_enabled=False,
    )


def _fake_noauth_settings() -> SimpleNamespace:
    # No Keycloak attributes at all: the endpoint must not touch them.
    return SimpleNamespace(
        auth_disabled=True,
        server_origin="http://localhost:8000",
    )


def test_integration_reports_keycloak_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "get_settings", _fake_settings)
    body = integration.integration()
    assert body["auth_disabled"] is False
    assert body["keycloak_issuer"] == "https://auth.example.com/realms/master"
    assert body["mcp_url"] == "https://instructions.example.com/kits/mcp"


def test_integration_auth_disabled_nulls_keycloak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(integration, "get_settings", _fake_noauth_settings)
    body = integration.integration()
    assert body["auth_disabled"] is True
    assert body["keycloak_issuer"] is None
    assert body["authorization_endpoint"] is None
    assert body["token_endpoint"] is None
    assert body["copilot_auth_enabled"] is False
    # Non-auth fields are still populated.
    assert body["mcp_url"] == "http://localhost:8000/kits/mcp"
    assert body["client_registration_url"] == (
        "http://localhost:8000/api/clients"
    )
