"""
Tests for the dev-only auth bypass (module-dev-auth-bypass).

Covers the kit's required cases: HS256 accepted only when the dev secret is
set, rejected otherwise; unknown algorithms rejected; dev tokens enforce the
same iss/aud; real RS256 is never routed to the dev validator; and the
dev-login router is a 404 unless explicitly enabled.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import JWTAuthMiddleware, _select_token_validation_mode
from app.config import Settings, get_settings
from app.dev_auth import decode_dev_token, mint_dev_token

# A dev secret of adequate length (>= 32 bytes) to avoid HMAC warnings.
SECRET = "dev-shared-secret-0123456789-abcdefghij"


def _settings(dev_secret: str | None = None, audience: str | None = None):
    return SimpleNamespace(
        oauth_metadata_url=(
            "https://x.example.com/.well-known/oauth-protected-resource"
        ),
        jwks_url=(
            "https://auth.example.com/realms/master/"
            "protocol/openid-connect/certs"
        ),
        keycloak_issuer="https://auth.example.com/realms/master",
        keycloak_audience=audience,
        tls_ca_bundle=None,
        tls_insecure_skip_verify=False,
        copilot_auth_enabled=False,
        copilot_auth_timeout_seconds=3.0,
        token_endpoint=(
            "https://auth.example.com/realms/master/"
            "protocol/openid-connect/token"
        ),
        dev_shared_secret=dev_secret,
    )


def _token_with_alg(alg: str) -> str:
    """Craft a token whose unverified header has the given alg."""

    def seg(obj: dict) -> str:
        return (
            base64.urlsafe_b64encode(json.dumps(obj).encode())
            .rstrip(b"=")
            .decode()
        )

    return f"{seg({'alg': alg, 'typ': 'JWT'})}.{seg({})}.sig"


# ---------------------------------------------------------------------------
# alg-header routing
# ---------------------------------------------------------------------------


def test_hs256_routes_to_dev_only_when_secret_set() -> None:
    tok = mint_dev_token(cast(Settings, _settings(SECRET)))
    assert (
        _select_token_validation_mode(tok, _settings(SECRET))
        == "dev-shared-secret"
    )


def test_hs256_rejected_when_secret_unset() -> None:
    tok = mint_dev_token(cast(Settings, _settings(SECRET)))
    with pytest.raises(jwt.InvalidTokenError):
        _select_token_validation_mode(tok, _settings(None))


def test_rs256_routes_to_jwks_not_dev() -> None:
    mode = _select_token_validation_mode(
        _token_with_alg("RS256"), _settings(SECRET)
    )
    assert mode == "oidc-jwks"


def test_unknown_alg_rejected() -> None:
    with pytest.raises(jwt.InvalidTokenError):
        _select_token_validation_mode(
            _token_with_alg("none"), _settings(SECRET)
        )


# ---------------------------------------------------------------------------
# dev tokens satisfy the same contract
# ---------------------------------------------------------------------------


def test_dev_token_round_trip() -> None:
    s = _settings(SECRET)
    claims = decode_dev_token(
        mint_dev_token(cast(Settings, s), username="alice"), cast(Settings, s)
    )
    assert claims["preferred_username"] == "alice"
    assert claims["iss"] == s.keycloak_issuer


def test_dev_token_wrong_issuer_rejected() -> None:
    minted = mint_dev_token(cast(Settings, _settings(SECRET)))
    other = _settings(SECRET)
    other.keycloak_issuer = "https://evil.example.com/realms/other"
    with pytest.raises(jwt.InvalidIssuerError):
        decode_dev_token(minted, cast(Settings, other))


def test_dev_token_missing_audience_rejected() -> None:
    # Minted without aud, but the validator requires one.
    minted = mint_dev_token(cast(Settings, _settings(SECRET)))
    with pytest.raises(jwt.PyJWTError):
        decode_dev_token(minted, cast(Settings, _settings(SECRET, "myaud")))


# ---------------------------------------------------------------------------
# middleware acceptance (isolated app, no UA gate)
# ---------------------------------------------------------------------------


def _auth_client(settings) -> TestClient:
    app = FastAPI()

    @app.get("/api/protected")
    async def protected() -> dict:
        return {"ok": True}

    app.add_middleware(JWTAuthMiddleware, settings=cast(Settings, settings))
    return TestClient(app)


def test_middleware_accepts_dev_token_when_secret_set() -> None:
    s = _settings(SECRET)
    token = mint_dev_token(cast(Settings, s))
    client = _auth_client(s)
    resp = client.get(
        "/api/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200


def test_middleware_rejects_hs256_when_secret_unset() -> None:
    token = mint_dev_token(cast(Settings, _settings(SECRET)))
    client = _auth_client(_settings(None))  # middleware has no dev secret
    resp = client.get(
        "/api/protected", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# router is a 404 unless enabled
# ---------------------------------------------------------------------------


def _make_app(monkeypatch, tmp_path: Path, **env):
    base = {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(tmp_path / "kits"),
        "WEBUI_DIST": "/nonexistent",
    }
    (tmp_path / "kits").mkdir(exist_ok=True)
    base.update(env)
    for key, value in base.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


def test_dev_login_404_when_disabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_app(monkeypatch, tmp_path)
    assert client.get("/auth/dev/token").status_code == 404
    get_settings.cache_clear()


def test_dev_login_mints_when_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_app(
        monkeypatch,
        tmp_path,
        DEV_AUTH_ENABLED="true",
        DEV_SHARED_SECRET=SECRET,
    )
    resp = client.get("/auth/dev/token?username=alice")
    assert resp.status_code == 200
    assert resp.json()["token_type"] == "Bearer"
    assert resp.json()["access_token"]
    get_settings.cache_clear()


def test_dev_login_503_when_secret_unset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = _make_app(monkeypatch, tmp_path, DEV_AUTH_ENABLED="true")
    assert client.get("/auth/dev/token").status_code == 503
    get_settings.cache_clear()
