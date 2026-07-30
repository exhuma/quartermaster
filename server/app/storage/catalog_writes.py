"""
Filesystem write primitives for a layered directory catalog.

This is the write half of generic catalog storage (the read half is
catalog-type-specific, e.g. ``app.kits`` for kits). It performs durable
filesystem effects only — no business logic, no validation of catalog
*content* (that is the service layer's job). Every mutation is atomic where
possible and confined to a given root so a malformed name can never escape
the catalog directory.

Nothing here knows about kits specifically; ``app.storage.kit_writes`` binds
these primitives to kit-shaped name/version/section validators.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path


class CatalogPathError(ValueError):
    """
    Raised for an invalid or unsafe catalog path component.

    Covers a malformed entry name, version label, or section basename, and
    any computed path that would escape the catalog root. A ``ValueError``
    subclass so existing ``except ValueError`` sites keep working.
    """


def validate_name(
    pattern: re.Pattern[str], value: str, *, description: str
) -> str:
    """
    Validate a path component against *pattern*.

    :param pattern: Compiled regex the value must fully match.
    :param value: Proposed path component.
    :param description: Human-readable description used in the error
        message, e.g. ``"kit name"``.
    :returns: *value* unchanged when valid.
    :raises CatalogPathError: If *value* does not fully match *pattern*.
    """
    if not pattern.fullmatch(value):
        raise CatalogPathError(
            f"Invalid {description} {value!r}: expected to match "
            f"{pattern.pattern!r}"
        )
    return value


def resolve_within(root: Path, *parts: str) -> Path:
    """
    Resolve *parts* under *root*, refusing any path that escapes it.

    :param root: The catalog root directory.
    :param parts: Path components to join under *root*.
    :returns: The resolved absolute path, guaranteed inside *root*.
    :raises CatalogPathError: If the result is outside *root*.
    """
    base = root.resolve()
    candidate = base.joinpath(*parts).resolve()
    if candidate != base and base not in candidate.parents:
        raise CatalogPathError(
            f"Refusing path outside catalog root: {candidate}"
        )
    return candidate


def atomic_write_text(path: Path, content: str) -> None:
    """
    Write *content* to *path* atomically (temp file + ``os.replace``).

    Creates parent directories as needed. A reader of *path* sees either
    the old or the new content, never a partial write.

    :param path: Destination file path.
    :param content: UTF-8 text to write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def remove_path(path: Path) -> None:
    """
    Delete *path* if it exists (file or directory tree). Idempotent.

    :param path: File or directory to remove.
    """
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def replace_dir(staging: Path, dest: Path) -> None:
    """
    Atomically replace directory *dest* with *staging*.

    *staging* and *dest* must live on the same filesystem (callers stage
    under the destination's parent to guarantee this). When *dest*
    already exists it is swapped out and removed only after the new
    directory is in place; on failure the original is restored.

    :param staging: Fully-populated replacement directory.
    :param dest: Target path to replace.
    """
    if not dest.exists():
        os.replace(staging, dest)
        return
    backup = dest.with_name(dest.name + ".bak")
    remove_path(backup)
    os.replace(dest, backup)
    try:
        os.replace(staging, dest)
    except BaseException:
        os.replace(backup, dest)
        raise
    remove_path(backup)
