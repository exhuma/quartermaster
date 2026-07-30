"""
Unit tests for the generic private-overlay primitives in isolation.

Covers :mod:`app.catalog.private_overlay` directly, parameterized on an
arbitrary ``base_root`` rather than any kit-specific settings — this is the
machinery ``app.private_kits`` binds to ``get_settings().private_kits_root``
for kits, and that a future second catalog type would bind to its own root.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.catalog.private_overlay import (
    _owner_dirname,
    owned_private_roots,
    private_root_for,
)


def test_owner_dirname_is_stable_and_hashed() -> None:
    """The owner directory name is a deterministic hash, not the raw subject."""
    name = _owner_dirname("alice-sub")
    assert name == _owner_dirname("alice-sub")
    assert "alice-sub" not in name
    assert len(name) == 16


def test_owner_dirname_differs_per_subject() -> None:
    """Distinct subjects hash to distinct directory names."""
    assert _owner_dirname("alice-sub") != _owner_dirname("bob-sub")


def test_private_root_for_confined_within_base(tmp_path: Path) -> None:
    """The resolved root lives under base_root, named by the owner hash."""
    root = private_root_for(tmp_path, "alice-sub")
    assert root.parent == tmp_path.resolve()
    assert root.name == _owner_dirname("alice-sub")


def test_private_root_for_empty_subject_raises(tmp_path: Path) -> None:
    """An empty subject is rejected rather than silently resolving a root."""
    with pytest.raises(ValueError):
        private_root_for(tmp_path, "")


def test_owned_private_roots_empty_without_subject(tmp_path: Path) -> None:
    """No subject (unauthenticated caller) always yields no private roots."""
    assert owned_private_roots(tmp_path, None) == []
    assert owned_private_roots(tmp_path, "") == []


def test_owned_private_roots_empty_when_not_yet_created(
    tmp_path: Path,
) -> None:
    """A subject with no private catalog on disk yet yields no roots."""
    assert owned_private_roots(tmp_path, "alice-sub") == []


def test_owned_private_roots_present_once_created(tmp_path: Path) -> None:
    """Once the owner's directory exists on disk, it is returned."""
    root = private_root_for(tmp_path, "alice-sub")
    root.mkdir(parents=True)
    assert owned_private_roots(tmp_path, "alice-sub") == [root]


def test_owned_private_roots_isolated_per_subject(tmp_path: Path) -> None:
    """A different subject's private root is never returned for another."""
    alice_root = private_root_for(tmp_path, "alice-sub")
    alice_root.mkdir(parents=True)
    assert owned_private_roots(tmp_path, "bob-sub") == []
