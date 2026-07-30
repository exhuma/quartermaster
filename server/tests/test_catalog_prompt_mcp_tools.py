"""
Tests for the ``list_catalog_prompts`` / ``get_catalog_prompt`` /
``create_catalog_prompt`` / ``update_catalog_prompt`` /
``delete_catalog_prompt`` MCP tools in ``app.main``.

These are distinct from the pre-existing ``list_prompts``/``get_prompt``
tools (canned onboarding templates, ``app.prompts``) — not touched here.
Mirrors ``tests/test_memory_tools.py``'s style: call the tool functions
directly, with identity bound via the contextvar.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import main as main_module
from app.identity import reset_identity, set_identity


@pytest.fixture()
def prompt_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shared = tmp_path / "prompts"
    shared.mkdir()
    from app.config import KitLayerConfig

    layers = [KitLayerConfig(name="default", path=shared, readonly=False)]
    settings = SimpleNamespace(
        effective_prompt_layers=layers,
        private_prompts_root=tmp_path / "private-prompts",
    )
    monkeypatch.setattr("app.prompt_catalog.get_settings", lambda: settings)
    monkeypatch.setattr("app.private_prompts.get_settings", lambda: settings)
    return shared


def _as_alice():
    return set_identity("alice-sub", "Alice")


def test_create_catalog_prompt_requires_authentication(
    prompt_settings: Path,
) -> None:
    with pytest.raises(ValueError):
        main_module.create_catalog_prompt("x", "body")


def test_create_read_update_delete_round_trip(prompt_settings: Path) -> None:
    tokens = _as_alice()
    try:
        created = main_module.create_catalog_prompt(
            "my-notes", "Initial body.", title="Notes", description="Mine."
        )
        assert created == {
            "name": "my-notes",
            "title": "Notes",
            "description": "Mine.",
            "body": "Initial body.",
        }

        fetched = main_module.get_catalog_prompt("my-notes")
        assert fetched["body"] == "Initial body."

        updated = main_module.update_catalog_prompt(
            "my-notes", "New body.", title="Notes v2"
        )
        assert updated["body"] == "New body."
        assert updated["title"] == "Notes v2"
        assert main_module.get_catalog_prompt("my-notes")["body"] == "New body."

        main_module.delete_catalog_prompt("my-notes")
        with pytest.raises(ValueError):
            main_module.get_catalog_prompt("my-notes")
    finally:
        reset_identity(tokens)


def test_create_catalog_prompt_only_touches_private_overlay(
    prompt_settings: Path, tmp_path: Path
) -> None:
    tokens = _as_alice()
    try:
        main_module.create_catalog_prompt("private-only", "Body.")
    finally:
        reset_identity(tokens)

    # Nothing was written to the shared catalog root.
    assert list(prompt_settings.glob("*.md")) == []
    # But it exists under alice's private overlay root.
    from app.private_prompts import private_root_for

    alice_root = private_root_for("alice-sub")
    assert (alice_root / "private-only.md").exists()


def test_other_user_cannot_see_or_delete_someone_elses_private_prompt(
    prompt_settings: Path,
) -> None:
    tokens = _as_alice()
    try:
        main_module.create_catalog_prompt("alice-only", "Body.")
    finally:
        reset_identity(tokens)

    tokens = set_identity("bob-sub", "Bob")
    try:
        names = {p["name"] for p in main_module.list_catalog_prompts()}
        assert "alice-only" not in names
        with pytest.raises(ValueError):
            main_module.get_catalog_prompt("alice-only")
        # Deleting a name bob doesn't own is a no-op (scoped to his own
        # private root, never alice's).
        main_module.delete_catalog_prompt("alice-only")
    finally:
        reset_identity(tokens)

    tokens = _as_alice()
    try:
        # Alice's copy survived bob's no-op delete attempt.
        assert main_module.get_catalog_prompt("alice-only")["body"] == "Body."
    finally:
        reset_identity(tokens)


def test_list_catalog_prompts_merges_shared_and_private(
    prompt_settings: Path,
) -> None:
    (prompt_settings / "shared-one.md").write_text(
        "Shared body.", encoding="utf-8"
    )
    tokens = _as_alice()
    try:
        main_module.create_catalog_prompt("alice-notes", "Notes.")
        names = {p["name"] for p in main_module.list_catalog_prompts()}
        assert names == {"shared-one", "alice-notes"}
    finally:
        reset_identity(tokens)

    # Public/unauthenticated view sees only the shared entry.
    assert {p["name"] for p in main_module.list_catalog_prompts()} == {
        "shared-one"
    }


def test_create_catalog_prompt_rejects_reserved_canned_name(
    prompt_settings: Path,
) -> None:
    tokens = _as_alice()
    try:
        with pytest.raises(ValueError):
            main_module.create_catalog_prompt("greet", "Body.")
    finally:
        reset_identity(tokens)


def test_delete_catalog_prompt_requires_authentication(
    prompt_settings: Path,
) -> None:
    with pytest.raises(ValueError):
        main_module.delete_catalog_prompt("x")
