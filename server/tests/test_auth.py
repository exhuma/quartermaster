"""Tests for authentication middleware modes."""

from __future__ import annotations

import ssl
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import IDPUnavailableError, JWTAuthMiddleware, _build_ssl_context
from app.config import Settings
from app.storage import app_tokens


def _settings(
    *,
    copilot_auth_enabled: bool,
    app_tokens_path: object = Path("/nonexistent/tokens.json"),
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
        tls_ca_bundle=None,
        tls_insecure_skip_verify=False,
        copilot_auth_enabled=copilot_auth_enabled,
        copilot_auth_timeout_seconds=3.0,
        token_endpoint=(
            "https://auth.example.com/realms/master/"
            "protocol/openid-connect/token"
        ),
        app_tokens_path=app_tokens_path,
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

    @app.get("/kits/probe")
    async def kits_probe() -> dict[str, str]:
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
    assert response.json()["detail"] == (
        "Missing or malformed Authorization header"
    )


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

    async def _valid(self: JWTAuthMiddleware, request: object) -> bool:
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

    async def _invalid(self: JWTAuthMiddleware, request: object) -> bool:
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
    assert response.json()["detail"] == (
        "Missing or malformed Authorization header"
    )


def test_bearer_takes_precedence_over_fixed_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure malformed bearer header is not bypassed by fixed headers."""

    def _invalid_token(self: JWTAuthMiddleware, token: str) -> dict:
        del token
        raise jwt.PyJWTError("bad token")

    monkeypatch.setattr(
        JWTAuthMiddleware, "_validate_bearer_token", _invalid_token
    )

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
    # The raw pyjwt exception text must not leak to the client.
    assert response.json()["detail"] == "Invalid token"


def test_fixed_headers_return_503_when_idp_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure IDP outages are surfaced as 503 errors."""

    async def _unavailable(self: JWTAuthMiddleware, request: object) -> bool:
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


def test_app_token_bearer_authenticates_mcp(tmp_path: Path) -> None:
    """A long-lived app token works as a Bearer credential on the MCP mount.

    opencode cannot refresh OIDC tokens, so it mints an app token and sends it
    as ``Authorization: Bearer <token>``. The token is not a JWT, so it falls
    through the JWT validator into the app-token fallback.
    """
    tokens = tmp_path / "tokens.json"
    _record, token = app_tokens.mint(tokens, "sub-123", "opencode")
    client = _client(
        _settings(copilot_auth_enabled=False, app_tokens_path=tokens)
    )
    resp = client.get(
        "/kits/probe", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


def test_app_token_bearer_authenticates_rest_api(tmp_path: Path) -> None:
    """The same app token also authenticates the REST API (both surfaces)."""
    tokens = tmp_path / "tokens.json"
    _record, token = app_tokens.mint(tokens, "sub-123", "opencode")
    client = _client(
        _settings(copilot_auth_enabled=False, app_tokens_path=tokens)
    )
    resp = client.get(
        "/api/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


def test_bogus_bearer_token_is_rejected(tmp_path: Path) -> None:
    """A bearer value that is neither a JWT nor a known app token → 401."""
    tokens = tmp_path / "tokens.json"
    app_tokens.mint(tokens, "sub-123", "opencode")  # some token exists
    client = _client(
        _settings(copilot_auth_enabled=False, app_tokens_path=tokens)
    )
    resp = client.get(
        "/api/protected",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid token"


def test_revoked_app_token_is_rejected(tmp_path: Path) -> None:
    """Revoking an app token invalidates it as a bearer credential at once."""
    tokens = tmp_path / "tokens.json"
    record, token = app_tokens.mint(tokens, "sub-123", "opencode")
    client = _client(
        _settings(copilot_auth_enabled=False, app_tokens_path=tokens)
    )
    ok = client.get(
        "/api/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert ok.status_code == 200

    assert app_tokens.revoke(tokens, record["id"], "sub-123") is True
    revoked = client.get(
        "/api/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked.status_code == 401


def test_valid_jwt_still_authenticates_when_app_tokens_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine JWT authenticates unchanged; the app-token fallback is a
    fallback only and never shadows real JWT validation."""
    tokens = tmp_path / "tokens.json"
    app_tokens.mint(tokens, "sub-123", "opencode")

    def _valid_token(self: JWTAuthMiddleware, token: str) -> dict:
        del token
        return {"sub": "jwt-user", "preferred_username": "alice"}

    monkeypatch.setattr(
        JWTAuthMiddleware, "_validate_bearer_token", _valid_token
    )
    client = _client(
        _settings(copilot_auth_enabled=False, app_tokens_path=tokens)
    )
    resp = client.get(
        "/api/protected", headers={"Authorization": "Bearer real.jwt.token"}
    )
    assert resp.status_code == 200


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


def _self_signed_ca_pem() -> str:
    """Generate a throwaway self-signed CA certificate as PEM text."""
    from datetime import datetime, timedelta

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test CA")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def _tls_settings(**overrides: object) -> Settings:
    """Build Settings for TLS-context tests (kits_root comes from env)."""
    base: dict[str, object] = {
        "keycloak_url": "https://auth.example.com",
        "keycloak_realm": "master",
        "resource_base_url": "https://instructions.example.com",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_ssl_context_default_is_none() -> None:
    """No TLS options set → callers use the default trust store."""
    assert _build_ssl_context(_tls_settings()) is None


def test_ssl_context_insecure_disables_verification() -> None:
    """Insecure flag → a context that checks neither cert nor hostname."""
    context = _build_ssl_context(_tls_settings(tls_insecure_skip_verify=True))
    assert context is not None
    assert context.check_hostname is False
    assert context.verify_mode == ssl.CERT_NONE


def test_ssl_context_insecure_takes_precedence_over_ca_bundle() -> None:
    """Insecure wins even when a CA bundle is also configured."""
    context = _build_ssl_context(
        _tls_settings(
            tls_insecure_skip_verify=True,
            tls_ca_bundle="/nonexistent/ca.pem",
        )
    )
    assert context is not None
    assert context.verify_mode == ssl.CERT_NONE


def test_ssl_context_ca_bundle_is_loaded(tmp_path: Path) -> None:
    """A CA bundle path → a verifying context built from that bundle."""
    ca_pem = tmp_path / "ca.pem"
    ca_pem.write_text(_self_signed_ca_pem(), encoding="utf-8")
    context = _build_ssl_context(_tls_settings(tls_ca_bundle=str(ca_pem)))
    assert context is not None
    assert context.verify_mode == ssl.CERT_REQUIRED
    # The bundle's certificate is loaded into the trust store.
    assert context.get_ca_certs()


def test_ssl_context_missing_ca_bundle_raises() -> None:
    """A nonexistent CA bundle fails loudly rather than silently."""
    with pytest.raises((FileNotFoundError, ssl.SSLError, OSError)):
        _build_ssl_context(_tls_settings(tls_ca_bundle="/nonexistent/ca.pem"))
