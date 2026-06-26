"""
Kit CRUD business logic (validate-before-commit).

Every mutation here assembles the *proposed* end-state in a staging area,
validates it with the very same loaders the read path uses
(:func:`app.kits._load_kit_index`, :func:`app.kits._validate_manifest`),
and only then atomically commits it to the catalog. A write that would
leave the catalog unable to load is rejected with
:class:`~app.kits.KitValidationError` and the on-disk state is untouched.

The layer reuses ``app.kits`` for all reads and path resolution so there is
a single source of truth for both discovery and validation. It obtains the
kits root via ``app.kits.get_settings`` (the same indirection reads use),
so tests that monkeypatch that callable affect writes too.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app import kits as kits_mod
from app.kits import (
    KitConflictError,
    KitNotFoundError,
    KitValidationError,
)
from app.storage import kit_writes as writes

__all__ = [
    "SectionInput",
    "list_kits",
    "get_kit_detail",
    "create_kit",
    "delete_kit",
    "get_applicability",
    "get_changelog",
    "replace_applicability",
    "list_versions",
    "create_version",
    "delete_version",
    "get_section",
    "put_section",
    "delete_section",
]


@dataclass(frozen=True)
class SectionInput:
    """
    A section to write into a kit version's ``instructions/`` directory.

    :param file: Section file basename, e.g. ``"invariant.md"``.
    :param title: Human-readable section title.
    :param gloss: One-line outline summary.
    :param always_load: Whether the section holds always-load invariants.
    :param body: Markdown body to write into the section file.
    """

    file: str
    title: str
    gloss: str
    always_load: bool
    body: str


def _kits_root() -> Path:
    """Return the configured kits root (honouring test monkeypatching)."""
    return Path(kits_mod.get_settings().kits_root)


def _toml_basic_string(value: str) -> str:
    """
    Render *value* as a TOML basic (double-quoted) string.

    Section titles/glosses and the kit summary are single-line free text;
    control characters and quotes are escaped per the TOML spec. The
    rendered index is always re-parsed by ``_load_kit_index`` before
    commit, so any emitter mistake is caught before reaching disk.

    :param value: Text to render.
    :returns: A quoted, escaped TOML basic string.
    """
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def _render_index_toml(summary: str, sections: list[dict[str, Any]]) -> str:
    """
    Render an ``index.toml`` document from a summary and section list.

    :param summary: Kit version summary.
    :param sections: Ordered section dicts with keys ``file``, ``title``,
        ``gloss``, ``always_load``.
    :returns: TOML text with a ``summary`` and ordered ``[[sections]]``.
    """
    lines = [f"summary = {_toml_basic_string(summary)}", ""]
    for section in sections:
        lines.append("[[sections]]")
        lines.append(f"file = {_toml_basic_string(section['file'])}")
        lines.append(f"title = {_toml_basic_string(section['title'])}")
        lines.append(f"gloss = {_toml_basic_string(section.get('gloss', ''))}")
        flag = "true" if section["always_load"] else "false"
        lines.append(f"always_load = {flag}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def _populate_instructions(
    instr_dir: Path, summary: str, sections: list[SectionInput]
) -> None:
    """
    Write section bodies and an ``index.toml`` into *instr_dir*.

    :param instr_dir: Target ``instructions/`` directory (created here).
    :param summary: Kit version summary.
    :param sections: Sections to write, in document order.
    """
    instr_dir.mkdir(parents=True, exist_ok=True)
    for section in sections:
        writes.validate_section_file(section.file)
        writes.atomic_write_text(instr_dir / section.file, section.body)
    index_text = _render_index_toml(
        summary,
        [
            {
                "file": s.file,
                "title": s.title,
                "gloss": s.gloss,
                "always_load": s.always_load,
            }
            for s in sections
        ],
    )
    writes.atomic_write_text(instr_dir / "index.toml", index_text)


def _validate_instructions(instr_dir: Path, name: str) -> None:
    """
    Validate a staged ``instructions/`` directory, raising on failure.

    :param instr_dir: Staged directory containing ``index.toml``.
    :param name: Kit name (for error messages).
    :raises KitValidationError: If the index or its sections are invalid.
    """
    try:
        kits_mod._load_kit_index(instr_dir / "index.toml", name)
    except (ValueError, FileNotFoundError) as exc:
        raise KitValidationError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Reads (delegate to app.kits)
# ---------------------------------------------------------------------------


def list_kits() -> list[dict[str, Any]]:
    """
    List all kits with compact metadata.

    :returns: List of ``{name, description, versions, latest_version}``.
    """
    return [
        {
            "name": kit.name,
            "description": kit.description,
            "versions": kit.versions,
            "latest_version": kit.latest_version,
        }
        for kit in kits_mod.list_all_kits()
    ]


def _require_kit(name: str) -> None:
    """Raise :class:`KitNotFoundError` if *name* is not a known kit."""
    versions = kits_mod._kit_version_paths(_kits_root())
    if name not in versions:
        raise KitNotFoundError(name)


def get_kit_detail(name: str) -> dict[str, Any]:
    """
    Return detail for a single kit: versions and applicability summary.

    :param name: Kit name.
    :returns: ``{name, versions, latest_version, applicability}``.
    :raises KitNotFoundError: If the kit does not exist.
    """
    _require_kit(name)
    versions = list(kits_mod._kit_version_paths(_kits_root())[name].keys())
    return {
        "name": name,
        "versions": versions,
        "latest_version": max(versions, key=kits_mod._version_key),
        "applicability": get_applicability(name),
    }


def list_versions(name: str) -> list[str]:
    """
    List a kit's major versions, oldest first.

    :param name: Kit name.
    :returns: Version labels, e.g. ``["v1", "v2"]``.
    :raises KitNotFoundError: If the kit does not exist.
    """
    _require_kit(name)
    return list(kits_mod._kit_version_paths(_kits_root())[name].keys())


def get_applicability(name: str) -> dict[str, Any]:
    """
    Return the raw stored ``applicability.json`` for a kit.

    :param name: Kit name.
    :returns: The parsed manifest object as stored on disk.
    :raises KitNotFoundError: If the kit (or its manifest) is missing.
    """
    _require_kit(name)
    manifest_file = kits_mod._manifest_path(_kits_root(), name)
    if not manifest_file.exists():
        raise KitNotFoundError(name)
    return json.loads(manifest_file.read_text(encoding="utf-8"))


def get_changelog(name: str) -> str:
    """
    Return a kit's raw ``CHANGELOG.md`` text (empty if none on disk).

    :param name: Kit name.
    :returns: Changelog text, or ``""`` if the file is absent.
    :raises KitNotFoundError: If the kit does not exist.
    """
    _require_kit(name)
    path = writes.resolve_within(_kits_root(), name, "CHANGELOG.md")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def get_section(
    name: str, version: str, section_id: str
) -> dict[str, Any]:
    """
    Return one section's metadata and body.

    :param name: Kit name.
    :param version: Version label.
    :param section_id: Section id (the file stem).
    :returns: ``{id, title, gloss, always_load, body}``.
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitSectionNotFoundError: If the section id is unknown.
    """
    outline = kits_mod.read_kit_outline(name, version)
    meta = next(
        (s for s in outline["sections"] if s["id"] == section_id), None
    )
    body = kits_mod.read_kit(name, version, sections=[section_id])
    return {
        "id": section_id,
        "title": meta["title"] if meta else section_id,
        "gloss": meta["gloss"] if meta else "",
        "always_load": bool(meta["always_load"]) if meta else False,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Writes (validate-before-commit)
# ---------------------------------------------------------------------------


def create_kit(
    name: str,
    applicability: dict[str, Any],
    summary: str,
    sections: list[SectionInput],
    changelog: str | None = None,
    version: str = "v1",
) -> dict[str, Any]:
    """
    Create a new kit with an initial version.

    Validates the applicability manifest and the proposed instruction
    index before committing; on success the whole kit directory appears
    atomically.

    :param name: New kit name.
    :param applicability: ``applicability.json`` content.
    :param summary: Initial version summary (``index.toml`` summary).
    :param sections: Initial sections (at least one required).
    :param changelog: Optional initial ``CHANGELOG.md`` text.
    :param version: Initial version label (default ``"v1"``).
    :returns: Kit detail (see :func:`get_kit_detail`).
    :raises KitConflictError: If the kit already exists.
    :raises KitValidationError: If the manifest or index is invalid.
    """
    writes.validate_kit_name(name)
    writes.validate_version(version)
    root = _kits_root()
    kit_dir = writes.resolve_within(root, name)
    if kit_dir.exists():
        raise KitConflictError(f"Kit already exists: {name!r}")
    if not sections:
        raise KitValidationError(
            f"Kit {name!r} must define at least one section"
        )
    try:
        kits_mod._validate_manifest(applicability, name)
    except ValueError as exc:
        raise KitValidationError(str(exc)) from exc

    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        staging = Path(tmp) / name
        _populate_instructions(
            staging / version / "instructions", summary, sections
        )
        writes.atomic_write_text(
            staging / "applicability.json",
            json.dumps(applicability, indent=2) + "\n",
        )
        default_changelog = (
            f"# Changelog\n\n## {version}.0.0\n\nInitial release.\n"
        )
        writes.atomic_write_text(
            staging / "CHANGELOG.md", changelog or default_changelog
        )
        _validate_instructions(staging / version / "instructions", name)
        writes.replace_dir(staging, kit_dir)
    return get_kit_detail(name)


def delete_kit(name: str) -> None:
    """
    Delete a kit and all its versions. Idempotent.

    :param name: Kit name (no error if it does not exist).
    """
    writes.validate_kit_name(name)
    kit_dir = writes.resolve_within(_kits_root(), name)
    writes.remove_path(kit_dir)


def replace_applicability(
    name: str, applicability: dict[str, Any]
) -> dict[str, Any]:
    """
    Replace a kit's ``applicability.json`` (idempotent PUT).

    :param name: Kit name (must already exist).
    :param applicability: New manifest content.
    :returns: The stored manifest.
    :raises KitNotFoundError: If the kit does not exist.
    :raises KitValidationError: If the manifest is invalid.
    """
    _require_kit(name)
    try:
        kits_mod._validate_manifest(applicability, name)
    except ValueError as exc:
        raise KitValidationError(str(exc)) from exc
    manifest_file = writes.resolve_within(
        _kits_root(), name, "applicability.json"
    )
    writes.atomic_write_text(
        manifest_file, json.dumps(applicability, indent=2) + "\n"
    )
    return get_applicability(name)


def create_version(
    name: str,
    version: str,
    summary: str,
    sections: list[SectionInput],
) -> list[str]:
    """
    Add a new major version to an existing kit.

    :param name: Kit name (must exist).
    :param version: New version label, e.g. ``"v2"``.
    :param summary: Version summary.
    :param sections: Sections for the new version (at least one).
    :returns: Updated version list.
    :raises KitNotFoundError: If the kit does not exist.
    :raises KitConflictError: If the version already exists.
    :raises KitValidationError: If the proposed index is invalid.
    """
    _require_kit(name)
    writes.validate_version(version)
    if not sections:
        raise KitValidationError(
            f"Version {version!r} of kit {name!r} must define at least "
            f"one section"
        )
    root = _kits_root()
    version_dir = writes.resolve_within(root, name, version)
    if version_dir.exists():
        raise KitConflictError(
            f"Version {version!r} already exists for kit {name!r}"
        )
    kit_dir = writes.resolve_within(root, name)
    with tempfile.TemporaryDirectory(dir=kit_dir) as tmp:
        staging = Path(tmp) / "instructions"
        _populate_instructions(staging, summary, sections)
        _validate_instructions(staging, name)
        version_dir.mkdir(parents=True, exist_ok=True)
        writes.replace_dir(staging, version_dir / "instructions")
    return list_versions(name)


def delete_version(name: str, version: str) -> list[str]:
    """
    Delete one major version of a kit. Idempotent.

    :param name: Kit name (must exist).
    :param version: Version label to remove (no error if absent).
    :returns: Updated version list.
    :raises KitNotFoundError: If the kit does not exist.
    """
    _require_kit(name)
    writes.validate_version(version)
    version_dir = writes.resolve_within(_kits_root(), name, version)
    writes.remove_path(version_dir)
    return list_versions(name)


def _rewrite_instructions(
    name: str, version: str, transform: Callable[[Path], None]
) -> None:
    """
    Apply *transform* to a staged copy of a version's instructions.

    Copies the live ``instructions/`` directory into a staging area,
    lets *transform* mutate it, validates the result, then atomically
    swaps it into place. The live directory is never partially modified.

    :param name: Kit name.
    :param version: Version label.
    :param transform: Callable receiving the staging ``Path`` to mutate.
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitValidationError: If the transformed index is invalid.
    """
    _, index_path = kits_mod._resolve_kit_version(name, version)
    instr_dir = index_path.parent
    with tempfile.TemporaryDirectory(dir=instr_dir.parent) as tmp:
        staging = Path(tmp) / "instructions"
        shutil.copytree(instr_dir, staging)
        transform(staging)
        _validate_instructions(staging, name)
        writes.replace_dir(staging, instr_dir)


def _read_index_sections(instr_dir: Path) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(summary, sections)`` parsed from a staged index.toml."""
    raw = tomllib.loads((instr_dir / "index.toml").read_text(encoding="utf-8"))
    summary = str(raw.get("summary", ""))
    sections = [dict(s) for s in raw.get("sections", [])]
    return summary, sections


def put_section(
    name: str,
    version: str,
    section_id: str,
    title: str,
    gloss: str,
    always_load: bool,
    body: str,
) -> dict[str, Any]:
    """
    Create or replace a section (idempotent PUT).

    The section file is ``<section_id>.md``. When the id already exists
    its metadata and body are updated in place (document order
    preserved); otherwise it is appended.

    :param name: Kit name.
    :param version: Version label.
    :param section_id: Section id (file stem).
    :param title: Section title.
    :param gloss: One-line outline summary.
    :param always_load: Always-load flag.
    :param body: Markdown body.
    :returns: The stored section (see :func:`get_section`).
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitValidationError: If the result is invalid.
    """
    file = f"{section_id}.md"
    try:
        writes.validate_section_file(file)
    except ValueError as exc:
        raise KitValidationError(str(exc)) from exc

    def _transform(staging: Path) -> None:
        writes.atomic_write_text(staging / file, body)
        summary, sections = _read_index_sections(staging)
        entry = {
            "file": file,
            "title": title,
            "gloss": gloss,
            "always_load": always_load,
        }
        for pos, existing in enumerate(sections):
            if existing.get("file") == file:
                sections[pos] = entry
                break
        else:
            sections.append(entry)
        writes.atomic_write_text(
            staging / "index.toml", _render_index_toml(summary, sections)
        )

    _rewrite_instructions(name, version, _transform)
    return get_section(name, version, section_id)


def delete_section(name: str, version: str, section_id: str) -> list[str]:
    """
    Delete a section from a version. Idempotent for an absent section.

    :param name: Kit name.
    :param version: Version label.
    :param section_id: Section id to remove.
    :returns: Remaining section ids in document order.
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitValidationError: If removal would empty the index.
    """
    file = f"{section_id}.md"

    def _transform(staging: Path) -> None:
        summary, sections = _read_index_sections(staging)
        remaining = [s for s in sections if s.get("file") != file]
        if len(remaining) == len(sections):
            return  # absent: no-op
        writes.remove_path(staging / file)
        writes.atomic_write_text(
            staging / "index.toml", _render_index_toml(summary, remaining)
        )

    _rewrite_instructions(name, version, _transform)
    outline = kits_mod.read_kit_outline(name, version)
    return [s["id"] for s in outline["sections"]]
