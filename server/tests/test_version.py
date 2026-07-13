"""Tests for the shared app-version resolver (app/version.py)."""

from __future__ import annotations

import pytest

from app.version import app_channel, app_version


def test_env_override_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    """QM_APP_VERSION takes precedence over package metadata."""
    monkeypatch.setenv("QM_APP_VERSION", "2026.6.28-alpha.2")
    assert app_version() == "2026.6.28-alpha.2"


def test_blank_env_falls_back_to_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank/whitespace override is ignored; metadata is used instead."""
    monkeypatch.setenv("QM_APP_VERSION", "   ")
    # The package is installed in the test env, so this is the real version
    # rather than the "0.0.0" placeholder.
    assert app_version() == "0.1.0"


def test_no_env_uses_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no override set, the installed package metadata is reported."""
    monkeypatch.delenv("QM_APP_VERSION", raising=False)
    assert app_version() == "0.1.0"


def test_app_channel_defaults_to_alpha(monkeypatch: pytest.MonkeyPatch) -> None:
    """No channel baked in (dev/source) → the pre-release alpha default."""
    monkeypatch.delenv("QM_APP_CHANNEL", raising=False)
    assert app_channel() == "alpha"
    # A blank/whitespace value is treated as unset.
    monkeypatch.setenv("QM_APP_CHANNEL", "  ")
    assert app_channel() == "alpha"


def test_app_channel_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A baked channel (release build) is reported verbatim."""
    monkeypatch.setenv("QM_APP_CHANNEL", "beta")
    assert app_channel() == "beta"
