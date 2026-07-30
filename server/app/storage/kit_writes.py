"""
Filesystem write primitives for the kit catalog.

This is the write half of kit storage (the read half lives in
``app.kits``). It performs durable filesystem effects only — no business
logic, no validation of kit *content* (that is the service layer's job).
Every mutation is atomic where possible and confined to the kits root so
a malformed name can never escape the catalog directory.

The generic primitives (path confinement, atomic writes, directory swaps)
live in :mod:`app.storage.catalog_writes`; this module binds them to
kit-specific name/version/section validators and re-exports them under
their original names so existing call sites are unaffected.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.storage import catalog_writes
from app.storage.catalog_writes import (
    CatalogPathError,
    atomic_write_text,
    remove_path,
    replace_dir,
    validate_name,
)

__all__ = [
    "KitPathError",
    "validate_kit_name",
    "validate_version",
    "validate_section_file",
    "resolve_within",
    "atomic_write_text",
    "remove_path",
    "replace_dir",
]

# Kit directory names: lowercase words joined by single hyphens, matching
# the existing catalog convention (e.g. ``module-auth-oidc``).
_KIT_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Major version folders are ``v<N>`` (see app.kits._kit_version_paths).
_VERSION_RE = re.compile(r"v\d+")
# Section file basenames: a markdown file with a safe stem.
_SECTION_FILE_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md")


class KitPathError(CatalogPathError):
    """
    Raised for an invalid or unsafe kit path component.

    Covers a malformed kit name, version label, or section basename, and
    any computed path that would escape the kits root. A ``ValueError``
    subclass (via :class:`~app.storage.catalog_writes.CatalogPathError`) so
    existing ``except ValueError`` sites keep working.
    """


def validate_kit_name(name: str) -> str:
    """
    Validate a kit directory name.

    :param name: Proposed kit name.
    :returns: The name unchanged when valid.
    :raises KitPathError: If the name is not a safe kit directory name.
    """
    try:
        return validate_name(_KIT_NAME_RE, name, description="kit name")
    except CatalogPathError as exc:
        raise KitPathError(
            f"Invalid kit name {name!r}: expected lowercase words joined "
            f"by hyphens, e.g. 'module-auth-oidc'"
        ) from exc


def validate_version(version: str) -> str:
    """
    Validate a major version label.

    :param version: Proposed version, e.g. ``"v1"``.
    :returns: The version unchanged when valid.
    :raises KitPathError: If the version is not of the form ``v<N>``.
    """
    try:
        return validate_name(_VERSION_RE, version, description="version")
    except CatalogPathError as exc:
        raise KitPathError(
            f"Invalid version {version!r}: expected 'v<N>', e.g. 'v1'"
        ) from exc


def validate_section_file(file: str) -> str:
    """
    Validate a section file basename.

    :param file: Proposed section file, e.g. ``"invariant.md"``.
    :returns: The basename unchanged when valid.
    :raises KitPathError: If the basename is unsafe or not a ``.md`` file.
    """
    try:
        return validate_name(
            _SECTION_FILE_RE, file, description="section file"
        )
    except CatalogPathError as exc:
        raise KitPathError(
            f"Invalid section file {file!r}: expected a lowercase "
            f"hyphenated '.md' basename, e.g. 'invariant.md'"
        ) from exc


def resolve_within(root: Path, *parts: str) -> Path:
    """
    Resolve *parts* under *root*, refusing any path that escapes it.

    Thin wrapper over :func:`app.storage.catalog_writes.resolve_within`
    that translates the generic :class:`CatalogPathError` into
    :class:`KitPathError` for existing kit call sites.

    :param root: The kits root directory.
    :param parts: Path components to join under *root*.
    :returns: The resolved absolute path, guaranteed inside *root*.
    :raises KitPathError: If the result is outside *root*.
    """
    try:
        return catalog_writes.resolve_within(root, *parts)
    except CatalogPathError as exc:
        raise KitPathError(str(exc)) from exc
