"""Unit tests for the TOML-backed authorization role store."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.storage import role_store


def test_unknown_subject_defaults_to_consumer(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    assert role_store.get_role(path, "nobody") == role_store.CONSUMER


def test_set_and_get_editor_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    role_store.set_role(path, "sub-1", role_store.EDITOR, "Alice")
    assert role_store.get_role(path, "sub-1") == role_store.EDITOR
    # Persisted as TOML and reloadable.
    assert path.exists()
    reloaded = role_store.list_all(path)
    assert reloaded == [
        {
            "sub": "sub-1",
            "role": "editor",
            "label": "Alice",
            "updated": reloaded[0]["updated"],
            "source": "store",
        }
    ]
    assert reloaded[0]["updated"]  # a timestamp was stamped


def test_bootstrap_editor_always_wins(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    # Even with a stored consumer record, the env editor overrides.
    role_store.set_role(path, "boss", role_store.CONSUMER, "Boss")
    assert (
        role_store.get_role(path, "boss", initial_editors=["boss"])
        == role_store.EDITOR
    )


def test_bootstrap_editor_cannot_be_removed(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    with pytest.raises(ValueError):
        role_store.remove(path, "boss", initial_editors=["boss"])


def test_remove_reverts_to_default(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    role_store.set_role(path, "sub-2", role_store.EDITOR)
    assert role_store.remove(path, "sub-2") is True
    assert role_store.get_role(path, "sub-2") == role_store.CONSUMER
    # Idempotent.
    assert role_store.remove(path, "sub-2") is False


def test_set_role_rejects_unknown_role(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    with pytest.raises(ValueError):
        role_store.set_role(path, "sub-3", "superuser")


def test_list_all_unions_bootstrap_rows(tmp_path: Path) -> None:
    path = tmp_path / "roles.toml"
    role_store.set_role(path, "stored-editor", role_store.EDITOR)
    rows = role_store.list_all(path, initial_editors=["env-editor"])
    by_sub = {r["sub"]: r for r in rows}
    assert by_sub["env-editor"]["source"] == "bootstrap"
    assert by_sub["env-editor"]["role"] == "editor"
    assert by_sub["stored-editor"]["source"] == "store"


def test_comma_separated_bootstrap_editor_label_preserved(
    tmp_path: Path,
) -> None:
    """A bootstrap editor that also has a stored label shows that label once."""
    path = tmp_path / "roles.toml"
    role_store.set_role(path, "dual", role_store.EDITOR, "Dual Role")
    rows = role_store.list_all(path, initial_editors=["dual"])
    duals = [r for r in rows if r["sub"] == "dual"]
    assert len(duals) == 1
    assert duals[0]["source"] == "bootstrap"
    assert duals[0]["label"] == "Dual Role"
