"""Owner-scoped private prompt roots.

A private prompt is a single Markdown file that only its owner may see.
Private prompts live under a per-owner subtree of ``QM_PRIVATE_PROMPTS_ROOT``
— never the shared catalog — so a missed enumeration path cannot leak them,
and each owner's subtree is a self-contained unit.

The owner directory name is a hash of the stable subject, not the subject
itself: identity providers may hand out subjects that are not filesystem-safe,
so hashing sidesteps every path-escape question and keeps the raw subject off
disk. Reads/writes still pass through
:func:`~app.storage.catalog_writes.resolve_within` for defence in depth.

This module is a thin, prompt-specific binding over the generic
private-overlay machinery in :mod:`app.catalog.private_overlay`, fixed to
``get_settings().private_prompts_root`` as the base root — mirrors
``app.private_kits`` exactly, but for prompts.
"""

from __future__ import annotations

from pathlib import Path

from app.catalog.private_overlay import owned_private_roots as _owned_roots
from app.catalog.private_overlay import private_root_for as _private_root_for
from app.config import get_settings


def private_root_for(sub: str) -> Path:
    """
    Return the private-prompt catalog root for owner *sub*.

    :param sub: The owner's stable subject (must be non-empty).
    :returns: The absolute path to the owner's private catalog root
        (confined within ``private_prompts_root``; may not yet exist).
    :raises ValueError: If *sub* is empty.
    """
    base = get_settings().private_prompts_root
    return _private_root_for(Path(base), sub)


def owned_private_roots(sub: str | None) -> list[Path]:
    """
    Return the owner's private root(s) that currently exist on disk.

    :param sub: The caller's subject, or ``None`` for an unauthenticated caller.
    :returns: ``[root]`` when the owner has a private catalog, else ``[]``.
    """
    if not sub:
        return []
    base = get_settings().private_prompts_root
    return _owned_roots(Path(base), sub)
