"""Tests for the get_my_memory / reset_my_memory MCP tools."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main as main_module
from app.identity import reset_identity, set_identity
from app.storage import user_memory


@pytest.fixture()
def _memory_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "user-memory.toml"
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(
            user_memory_enabled=True, user_memory_store_path=path
        ),
    )
    return path


def test_get_my_memory_returns_empty_profile_when_none_derived(
    _memory_settings: Path,
) -> None:
    tokens = set_identity("alice", "Alice")
    try:
        result = main_module.get_my_memory()
    finally:
        reset_identity(tokens)
    assert result["updated"] is None
    assert result["top_kits"] == []


def test_get_my_memory_returns_stored_profile(_memory_settings: Path) -> None:
    user_memory.save_profile(
        _memory_settings,
        "alice",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": ["auth"],
            "top_kits": ["module-auth-oidc"],
            "top_languages": ["python"],
            "top_frameworks": [],
        },
    )
    tokens = set_identity("alice", "Alice")
    try:
        result = main_module.get_my_memory()
    finally:
        reset_identity(tokens)
    assert result["top_kits"] == ["module-auth-oidc"]


def test_get_my_memory_scoped_to_caller(_memory_settings: Path) -> None:
    user_memory.save_profile(
        _memory_settings,
        "bob",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": [],
            "top_kits": ["module-bob-only"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    tokens = set_identity("alice", "Alice")
    try:
        result = main_module.get_my_memory()
    finally:
        reset_identity(tokens)
    assert result["top_kits"] == []


def test_get_my_memory_empty_when_unauthenticated(
    _memory_settings: Path,
) -> None:
    result = main_module.get_my_memory()
    assert result["top_kits"] == []


def test_reset_my_memory_clears_and_is_idempotent(
    _memory_settings: Path,
) -> None:
    user_memory.save_profile(
        _memory_settings,
        "alice",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": [],
            "top_kits": ["module-auth-oidc"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    tokens = set_identity("alice", "Alice")
    try:
        assert main_module.reset_my_memory() == {"cleared": True}
        assert main_module.reset_my_memory() == {"cleared": False}
        assert main_module.get_my_memory()["top_kits"] == []
    finally:
        reset_identity(tokens)


def test_reset_my_memory_does_not_affect_other_subjects(
    _memory_settings: Path,
) -> None:
    user_memory.save_profile(
        _memory_settings,
        "bob",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": [],
            "top_kits": ["module-bob-only"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    tokens = set_identity("alice", "Alice")
    try:
        main_module.reset_my_memory()
    finally:
        reset_identity(tokens)
    assert user_memory.load_profile(_memory_settings, "bob")["top_kits"] == [
        "module-bob-only"
    ]


def test_reset_my_memory_false_when_unauthenticated(
    _memory_settings: Path,
) -> None:
    assert main_module.reset_my_memory() == {"cleared": False}


# ---------------------------------------------------------------------------
# Registration gate
# ---------------------------------------------------------------------------


def test_user_memory_enabled_true_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(user_memory_enabled=True),
    )
    assert main_module._user_memory_enabled() is True


def test_user_memory_enabled_false_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        main_module,
        "get_settings",
        lambda: SimpleNamespace(user_memory_enabled=False),
    )
    assert main_module._user_memory_enabled() is False


def test_user_memory_enabled_false_when_settings_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import ValidationError

    def _raise() -> SimpleNamespace:
        raise ValidationError.from_exception_data("Settings", [])

    monkeypatch.setattr(main_module, "get_settings", _raise)
    assert main_module._user_memory_enabled() is False
