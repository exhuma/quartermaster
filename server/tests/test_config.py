"""Tests for Settings validation, focused on auth-less mode.

``QM_AUTH_DISABLED`` relaxes the otherwise-required Keycloak configuration so a
trusted deployment can run without an IdP. These tests pin that contract: with
auth off, Keycloak may be absent and the computed Keycloak URLs collapse to
empty strings; with auth on (the default), missing Keycloak config is a loud
startup error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def _settings(**overrides: object) -> Settings:
    """Build Settings ignoring the repo ``.env`` so the test env is explicit."""
    base: dict[str, object] = {
        "_env_file": None,
        "resource_base_url": "http://localhost:8000",
        "kits_root": Path("/tmp"),
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def test_auth_disabled_allows_missing_keycloak() -> None:
    settings = _settings(auth_disabled=True)
    assert settings.auth_disabled is True
    assert settings.keycloak_url is None
    assert settings.keycloak_realm is None
    # Computed Keycloak URLs degrade to empty strings, never build from None.
    assert settings.jwks_url == ""
    assert settings.keycloak_issuer == ""
    assert settings.authorization_endpoint == ""
    assert settings.token_endpoint == ""


def test_auth_enabled_requires_keycloak() -> None:
    with pytest.raises(ValidationError) as excinfo:
        _settings(auth_disabled=False)
    assert "QM_KEYCLOAK_URL" in str(excinfo.value)


def test_auth_enabled_with_keycloak_builds_urls() -> None:
    settings = _settings(
        auth_disabled=False,
        keycloak_url="https://auth.example.com",
        keycloak_realm="master",
    )
    assert settings.jwks_url.startswith("https://auth.example.com/realms/master")
    assert settings.keycloak_issuer == "https://auth.example.com/realms/master"


def test_auth_disabled_defaults_off() -> None:
    settings = _settings(
        keycloak_url="https://auth.example.com",
        keycloak_realm="master",
    )
    assert settings.auth_disabled is False
