"""Tests for authentication middleware modes."""

from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import IDPUnavailableError, JWTAuthMiddleware
from app.config import Settings


def _settings(
    *,
    copilot_auth_enabled: bool,
) -> SimpleNamespace:
    """Return a settings-like object for auth middleware tests."""
    return SimpleNamespace(
        oauth_metadata_url=(
            "https://instructions.example.com/.well-known/"
            "oauth-protected-resource"
        ),
        jwks_url=(
            "https://auth.example.com/realms/master/"
            "protocol/openid-connect/certs"
        ),
        keycloak_issuer="https://auth.example.com/realms/master",
        keycloak_audience=None,
        copilot_auth_enabled=copilot_auth_enabled,
        copilot_auth_timeout_seconds=3.0,
        token_endpoint=(
            "https://auth.example.com/realms/master/"
            "protocol/openid-connect/token"
        ),
    )


def _client(settings: SimpleNamespace) -> TestClient:
    """Build a FastAPI app wrapped by auth middleware for testing."""
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/protected")
    async def protected() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(
        JWTAuthMiddleware,
        settings=cast(Settings, settings),
    )
    return TestClient(app)


def test_public_health_path_skips_auth() -> None:
    """Ensure public health path is reachable without credentials."""
    client = _client(_settings(copilot_auth_enabled=False))
    response = client.get("/health")
    assert response.status_code == 200


def test_missing_auth_returns_401() -> None:
    """Ensure protected routes reject unauthenticated requests."""
    client = _client(_settings(copilot_auth_enabled=False))
    response = client.get("/api/protected")
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or malformed Authorization header"


def test_spa_shell_path_is_public() -> None:
    """Non-/api, non-/kits paths (the SPA shell) skip auth."""
    from app.auth import _requires_auth

    assert _requires_auth("/api/kits") is True
    assert _requires_auth("/kits/mcp") is True
    assert _requires_auth("/") is False
    assert _requires_auth("/integration") is False
    assert _requires_auth("/config.js") is False
    assert _requires_auth("/assets/index-abc.js") is False


def test_fixed_headers_allow_access_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure fixed headers are accepted when feature flag is enabled."""

    def _valid(self: JWTAuthMiddleware, request: object) -> bool:
        del self, request
        return True

    monkeypatch.setattr(JWTAuthMiddleware, "_validate_copilot_headers", _valid)

    client = _client(
        _settings(
            copilot_auth_enabled=True,
        )
    )
    response = client.get(
        "/api/protected",
        headers={
            "X-Client-Id": "copilot-agent",
            "X-Client-Secret": "secret-1",
        },
    )
    assert response.status_code == 200


def test_fixed_headers_rejected_when_secret_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure invalid fixed header secret is rejected."""

    def _invalid(self: JWTAuthMiddleware, request: object) -> bool:
        del self, request
        return False

    monkeypatch.setattr(
        JWTAuthMiddleware,
        "_validate_copilot_headers",
        _invalid,
    )

    client = _client(
        _settings(
            copilot_auth_enabled=True,
        )
    )
    response = client.get(
        "/api/protected",
        headers={
            "X-Client-Id": "copilot-agent",
            "X-Client-Secret": "wrong-secret",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Copilot header credentials"


def test_fixed_headers_ignored_when_feature_disabled() -> None:
    """Ensure fixed headers do not authenticate when disabled."""
    client = _client(
        _settings(
            copilot_auth_enabled=False,
        )
    )
    response = client.get(
        "/api/protected",
        headers={
            "X-Client-Id": "copilot-agent",
            "X-Client-Secret": "secret-1",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing or malformed Authorization header"


def test_bearer_takes_precedence_over_fixed_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure malformed bearer header is not bypassed by fixed headers."""

    def _invalid_token(self: JWTAuthMiddleware, token: str) -> dict:
        del token
        raise jwt.PyJWTError("bad token")

    monkeypatch.setattr(JWTAuthMiddleware, "_validate_bearer_token", _invalid_token)

    client = _client(
        _settings(
            copilot_auth_enabled=True,
        )
    )
    response = client.get(
        "/api/protected",
        headers={
            "Authorization": "Bearer broken-token",
            "X-Client-Id": "copilot-agent",
            "X-Client-Secret": "secret-1",
        },
    )
    assert response.status_code == 401
    assert "Invalid token:" in response.json()["detail"]


def test_fixed_headers_return_503_when_idp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure IDP outages are surfaced as 503 errors."""

    def _unavailable(self: JWTAuthMiddleware, request: object) -> bool:
        del self, request
        raise IDPUnavailableError("idp down")

    monkeypatch.setattr(
        JWTAuthMiddleware,
        "_validate_copilot_headers",
        _unavailable,
    )

    client = _client(_settings(copilot_auth_enabled=True))
    response = client.get(
        "/api/protected",
        headers={
            "X-Client-Id": "copilot-agent",
            "X-Client-Secret": "secret-1",
        },
    )
    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]


def test_settings_default_copilot_auth_timeout() -> None:
    """Ensure timeout defaults for IDP-backed fixed-header auth."""
    settings = Settings(
        keycloak_url="https://auth.example.com",
        keycloak_realm="master",
        resource_base_url="https://instructions.example.com",
    )
    assert settings.copilot_auth_timeout_seconds == 3.0


def test_settings_allow_custom_copilot_auth_timeout() -> None:
    """Ensure timeout can be customized via settings."""
    settings = Settings(
        keycloak_url="https://auth.example.com",
        keycloak_realm="master",
        resource_base_url="https://instructions.example.com",
        copilot_auth_timeout_seconds=1.25,
    )
    assert settings.copilot_auth_timeout_seconds == 1.25
