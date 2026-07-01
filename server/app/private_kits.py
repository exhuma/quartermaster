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
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.config import get_settings
from app.storage.kit_writes import resolve_within


def _owner_dirname(sub: str) -> str:
    """Return the filesystem-safe directory name for owner *sub*."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:16]


def private_root_for(sub: str) -> Path:
    """
    Return the private-kit catalog root for owner *sub*.

    :param sub: The owner's stable subject (must be non-empty).
    :returns: The absolute path to the owner's private catalog root
        (confined within ``private_kits_root``; may not yet exist).
    :raises ValueError: If *sub* is empty.
    """
    if not sub:
        raise ValueError("A subject is required for a private-kit root.")
    base = get_settings().private_kits_root
    return resolve_within(Path(base), _owner_dirname(sub))


def owned_private_roots(sub: str | None) -> list[Path]:
    """
    Return the owner's private root(s) that currently exist on disk.

    :param sub: The caller's subject, or ``None`` for an unauthenticated caller.
    :returns: ``[root]`` when the owner has a private catalog, else ``[]``.
    """
    if not sub:
        return []
    root = private_root_for(sub)
    return [root] if root.is_dir() else []
