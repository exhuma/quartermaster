"""
Unit tests for the generic layering primitives in isolation.

Covers :mod:`app.catalog.layering` directly: it combines a catalog's
configured public layers with a per-caller private overlay, without knowing
anything about kits specifically (the private-root lookup is injected as a
plain callable).
"""

from __future__ import annotations

from pathlib import Path

from app.catalog.layering import (
    CTX_SUBJECT,
    PRIVATE_LAYER_NAME,
    caller_layers,
    resolve_subject,
)
from app.config import KitLayerConfig
from app.identity import reset_identity, set_identity


def test_resolve_subject_passes_through_explicit_values() -> None:
    """An explicit str or None subject is returned unchanged."""
    assert resolve_subject("alice-sub") == "alice-sub"
    assert resolve_subject(None) is None


def test_resolve_subject_reads_contextvar_for_sentinel() -> None:
    """CTX_SUBJECT reads the identity contextvar bound via app.identity."""
    assert resolve_subject(CTX_SUBJECT) is None
    tokens = set_identity("alice-sub", "Alice")
    try:
        assert resolve_subject(CTX_SUBJECT) == "alice-sub"
    finally:
        reset_identity(tokens)
    assert resolve_subject(CTX_SUBJECT) is None


def test_caller_layers_no_private_roots_returns_base_unchanged(
    tmp_path: Path,
) -> None:
    """A caller with no private roots sees exactly the public layers."""
    base = [KitLayerConfig(name="base", path=tmp_path, readonly=True)]
    layers = caller_layers(base, lambda _sub: [], subject="alice-sub")
    assert layers == base


def test_caller_layers_appends_private_overlay_last(tmp_path: Path) -> None:
    """A caller with an existing private root gets it appended, highest priority."""
    base = [KitLayerConfig(name="base", path=tmp_path, readonly=True)]
    private_dir = tmp_path / "alice-private"

    def _roots(sub: str | None) -> list[Path]:
        return [private_dir] if sub == "alice-sub" else []

    layers = caller_layers(base, _roots, subject="alice-sub")
    assert [l.name for l in layers] == ["base", PRIVATE_LAYER_NAME]
    assert layers[-1].path == private_dir
    assert layers[-1].readonly is False


def test_caller_layers_forced_public_ignores_private_roots(
    tmp_path: Path,
) -> None:
    """subject=None resolves to no subject, so a subject-gated
    private_roots_fn (the real-world shape, e.g. owned_private_roots)
    contributes nothing — public-only."""
    base = [KitLayerConfig(name="base", path=tmp_path, readonly=True)]

    def _roots(sub: str | None) -> list[Path]:
        # Mirrors owned_private_roots: no subject -> no private roots.
        return [tmp_path / "should-not-appear"] if sub else []

    layers = caller_layers(base, _roots, subject=None)
    assert layers == base


def test_caller_layers_uses_contextvar_by_default(tmp_path: Path) -> None:
    """The default subject argument (CTX_SUBJECT) reads ambient identity."""
    base = [KitLayerConfig(name="base", path=tmp_path, readonly=True)]
    private_dir = tmp_path / "alice-private"

    def _roots(sub: str | None) -> list[Path]:
        return [private_dir] if sub == "alice-sub" else []

    # No identity bound: public only.
    assert caller_layers(base, _roots) == base

    tokens = set_identity("alice-sub", "Alice")
    try:
        layers = caller_layers(base, _roots)
        assert layers[-1].path == private_dir
    finally:
        reset_identity(tokens)
    assert caller_layers(base, _roots) == base
