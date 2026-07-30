"""Owner-scoped private kit roots.

A private kit is a self-contained standalone kit (own name,
``applicability.json``, versions, sections) that only its owner may see.
Private kits live under a
per-owner subtree of ``QM_PRIVATE_KITS_ROOT`` — never the public catalog — so a
missed enumeration path cannot leak them, and each owner's subtree is a
self-contained unit that could later become an opaque encrypted blob (see
``docs/research/private-kits-e2ee.md``).

The owner directory name is a hash of the stable subject, not the subject
itself: Keycloak ``sub``s are UUIDs (safe) but Copilot client-ids and legacy
usernames may not be, so hashing sidesteps every path-escape question and keeps
the raw subject off disk. Reads/writes still pass through
:func:`~app.storage.kit_writes.resolve_within` for defence in depth.

This module is a thin, kit-specific binding over the generic private-overlay
machinery in :mod:`app.catalog.private_overlay`, fixed to
``get_settings().private_kits_root`` as the base root.
"""

from __future__ import annotations

from pathlib import Path

from app.catalog.private_overlay import owned_private_roots as _owned_roots
from app.catalog.private_overlay import private_root_for as _private_root_for
from app.config import get_settings


def private_root_for(sub: str) -> Path:
    """
    Return the private-kit catalog root for owner *sub*.

    :param sub: The owner's stable subject (must be non-empty).
    :returns: The absolute path to the owner's private catalog root
        (confined within ``private_kits_root``; may not yet exist).
    :raises ValueError: If *sub* is empty.
    """
    base = get_settings().private_kits_root
    return _private_root_for(Path(base), sub)


def owned_private_roots(sub: str | None) -> list[Path]:
    """
    Return the owner's private root(s) that currently exist on disk.

    :param sub: The caller's subject, or ``None`` for an unauthenticated caller.
    :returns: ``[root]`` when the owner has a private catalog, else ``[]``.
    """
    if not sub:
        return []
    base = get_settings().private_kits_root
    return _owned_roots(Path(base), sub)
