"""
Filesystem write primitives for the kit catalog.

This is the write half of kit storage (the read half lives in
``app.kits``). It performs durable filesystem effects only — no business
logic, no validation of kit *content* (that is the service layer's job).
Every mutation is atomic where possible and confined to the kits root so
a malformed name can never escape the catalog directory.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from pathlib import Path

# Kit directory names: lowercase words joined by single hyphens, matching
# the existing catalog convention (e.g. ``module-auth-oidc``).
_KIT_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Major version folders are ``v<N>`` (see app.kits._kit_version_paths).
_VERSION_RE = re.compile(r"v\d+")
# Section file basenames: a markdown file with a safe stem.
_SECTION_FILE_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\.md")


class KitPathError(ValueError):
    """
    Raised for an invalid or unsafe kit path component.

    Covers a malformed kit name, version label, or section basename, and
    any computed path that would escape the kits root. A ``ValueError``
    subclass so existing ``except ValueError`` sites keep working.
    """


def validate_kit_name(name: str) -> str:
    """
    Validate a kit directory name.

    :param name: Proposed kit name.
    :returns: The name unchanged when valid.
    :raises KitPathError: If the name is not a safe kit directory name.
    """
    if not _KIT_NAME_RE.fullmatch(name):
        raise KitPathError(
            f"Invalid kit name {name!r}: expected lowercase words joined "
            f"by hyphens, e.g. 'module-auth-oidc'"
        )
    return name


def validate_version(version: str) -> str:
    """
    Validate a major version label.

    :param version: Proposed version, e.g. ``"v1"``.
    :returns: The version unchanged when valid.
    :raises KitPathError: If the version is not of the form ``v<N>``.
    """
    if not _VERSION_RE.fullmatch(version):
        raise KitPathError(
            f"Invalid version {version!r}: expected 'v<N>', e.g. 'v1'"
        )
    return version


def validate_section_file(file: str) -> str:
    """
    Validate a section file basename.

    :param file: Proposed section file, e.g. ``"invariant.md"``.
    :returns: The basename unchanged when valid.
    :raises KitPathError: If the basename is unsafe or not a ``.md`` file.
    """
    if not _SECTION_FILE_RE.fullmatch(file):
        raise KitPathError(
            f"Invalid section file {file!r}: expected a lowercase "
            f"hyphenated '.md' basename, e.g. 'invariant.md'"
        )
    return file


def resolve_within(root: Path, *parts: str) -> Path:
    """
    Resolve *parts* under *root*, refusing any path that escapes it.

    :param root: The kits root directory.
    :param parts: Path components to join under *root*.
    :returns: The resolved absolute path, guaranteed inside *root*.
    :raises KitPathError: If the result is outside *root*.
    """
    base = root.resolve()
    candidate = base.joinpath(*parts).resolve()
    if candidate != base and base not in candidate.parents:
        raise KitPathError(
            f"Refusing path outside kits root: {candidate}"
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
