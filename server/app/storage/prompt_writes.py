"""
Filesystem write primitives for the prompts catalog.

Prompt content is a single Markdown file per prompt — no versions, no
sections — so, unlike kits, this module needs no directory-staging/swap
machinery: :func:`~app.storage.catalog_writes.atomic_write_text` alone is
sufficient and correct for a single-file write.

This is the write half of prompt storage (the read half lives in
``app.prompt_catalog``). It binds the generic primitives in
``app.storage.catalog_writes`` to a prompt-specific name validator and
re-exports the rest unchanged, mirroring ``app.storage.kit_writes``.
"""

from __future__ import annotations

import re

from app.storage.catalog_writes import (
    CatalogPathError,
    atomic_write_text,
    remove_path,
    resolve_within,
    validate_name,
)

__all__ = [
    "PromptPathError",
    "validate_prompt_name",
    "resolve_within",
    "atomic_write_text",
    "remove_path",
]

# Prompt file basenames (without extension): lowercase words joined by
# single hyphens, matching the kit-name convention.
_PROMPT_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class PromptPathError(CatalogPathError):
    """
    Raised for an invalid or unsafe prompt path component.

    A ``ValueError`` subclass (via
    :class:`~app.storage.catalog_writes.CatalogPathError`) so existing
    ``except ValueError`` sites keep working.
    """


def validate_prompt_name(name: str) -> str:
    """
    Validate a prompt name (the ``.md`` file's stem).

    :param name: Proposed prompt name.
    :returns: The name unchanged when valid.
    :raises PromptPathError: If the name is not a safe prompt name.
    """
    try:
        return validate_name(_PROMPT_NAME_RE, name, description="prompt name")
    except CatalogPathError as exc:
        raise PromptPathError(
            f"Invalid prompt name {name!r}: expected lowercase words "
            f"joined by hyphens, e.g. 'release-checklist'"
        ) from exc
