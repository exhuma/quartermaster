"""Owner-scoped private overlay roots for a layered directory catalog.

A private entry is a self-contained standalone catalog item (own name,
manifest, versions, sections) that only its owner may see. Private entries
live under a per-owner subtree of some catalog-specific private root — never
the public catalog — so a missed enumeration path cannot leak them, and each
owner's subtree is a self-contained unit that could later become an opaque
encrypted blob.

The owner directory name is a hash of the stable subject, not the subject
itself: identity providers may hand out subjects that are not filesystem-safe
(e.g. not UUIDs), so hashing sidesteps every path-escape question and keeps
the raw subject off disk. Reads/writes still pass through
:func:`~app.storage.catalog_writes.resolve_within` for defence in depth.

This module is generic over the catalog: callers pass the catalog-specific
private-root *base* directory in. ``app.private_kits`` binds it to
``get_settings().private_kits_root`` for kits.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.storage.catalog_writes import resolve_within


def _owner_dirname(sub: str) -> str:
    """Return the filesystem-safe directory name for owner *sub*."""
    return hashlib.sha256(sub.encode("utf-8")).hexdigest()[:16]


def private_root_for(base_root: Path, sub: str) -> Path:
    """
    Return the private overlay root for owner *sub* under *base_root*.

    :param base_root: The catalog-specific private-root base directory.
    :param sub: The owner's stable subject (must be non-empty).
    :returns: The absolute path to the owner's private catalog root
        (confined within *base_root*; may not yet exist).
    :raises ValueError: If *sub* is empty.
    """
    if not sub:
        raise ValueError("A subject is required for a private overlay root.")
    return resolve_within(Path(base_root), _owner_dirname(sub))


def owned_private_roots(base_root: Path, sub: str | None) -> list[Path]:
    """
    Return the owner's private root(s) that currently exist on disk.

    :param base_root: The catalog-specific private-root base directory.
    :param sub: The caller's subject, or ``None`` for an unauthenticated
        caller.
    :returns: ``[root]`` when the owner has a private catalog, else ``[]``.
    """
    if not sub:
        return []
    root = private_root_for(base_root, sub)
    return [root] if root.is_dir() else []
