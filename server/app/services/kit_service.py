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
    KitLayerNotFoundError,
    KitLayerReadonlyError,
    KitNotFoundError,
    KitValidationError,
)
from app.storage import kit_writes as writes

__all__ = [
    "SectionInput",
    "list_kits",
    "list_layers",
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


def _kits_write_root() -> Path:
    """Return the default writable layer root (last non-readonly layer)."""
    settings = kits_mod.get_settings()
    layers = kits_mod._get_effective_layers(settings)
    for layer in reversed(layers):
        if not layer.readonly:
            return layer.path
    raise RuntimeError(
        "No writable kit layer configured. "
        "Set QM_KITS_ROOT or configure at least one non-readonly layer "
        "in QM_KIT_LAYERS_FILE."
    )


def _layer_path(layer_id: str) -> Path:
    """
    Return the path for a named layer (read access, no readonly check).

    :param layer_id: Layer name as configured in QM_KIT_LAYERS_FILE.
    :raises KitLayerNotFoundError: If no such layer is configured.
    """
    settings = kits_mod.get_settings()
    layers = kits_mod._get_effective_layers(settings)
    for layer in layers:
        if layer.name == layer_id:
            return layer.path
    raise KitLayerNotFoundError(layer_id)


def _layer_write_path(layer_id: str) -> Path:
    """
    Return the path for a named layer and enforce it is writable.

    :param layer_id: Layer name as configured in QM_KIT_LAYERS_FILE.
    :raises KitLayerNotFoundError: If no such layer is configured.
    :raises KitLayerReadonlyError: If the layer has readonly=true.
    """
    settings = kits_mod.get_settings()
    layers = kits_mod._get_effective_layers(settings)
    for layer in layers:
        if layer.name == layer_id:
            if layer.readonly:
                raise KitLayerReadonlyError(layer_id)
            return layer.path
    raise KitLayerNotFoundError(layer_id)


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


def _require_kit(name: str, root: Path | None = None) -> None:
    """
    Raise :class:`KitNotFoundError` if *name* is not a known kit.

    When *root* is given, checks only that root (used by write ops that
    target a specific layer). When *root* is ``None``, checks the merged
    catalog across all configured layers.
    """
    if root is not None:
        if name not in kits_mod._kit_version_paths(root):
            raise KitNotFoundError(name)
    else:
        if not any(k.name == name for k in kits_mod.list_all_kits()):
            raise KitNotFoundError(name)


def list_layers() -> list[dict[str, Any]]:
    """
    Return metadata for all configured kit layers.

    :returns: List of ``{name, path, readonly}`` dicts, ordered base → overlay.
    """
    settings = kits_mod.get_settings()
    layers = kits_mod._get_effective_layers(settings)
    return [
        {
            "name": layer.name,
            "path": str(layer.path),
            "readonly": layer.readonly,
        }
        for layer in layers
    ]


def get_kit_detail(name: str, root: Path | None = None) -> dict[str, Any]:
    """
    Return detail for a single kit: versions and applicability summary.

    :param name: Kit name.
    :param root: When given, read from this root only (layer-specific).
    :returns: ``{name, versions, latest_version, applicability}``.
    :raises KitNotFoundError: If the kit does not exist.
    """
    if root is not None:
        _require_kit(name, root=root)
        versions = list(kits_mod._kit_version_paths(root)[name].keys())
        return {
            "name": name,
            "versions": versions,
            "latest_version": max(versions, key=kits_mod._version_key),
            "applicability": get_applicability(name, root=root),
        }
    # Merged view
    kit_info = next(
        (k for k in kits_mod.list_all_kits() if k.name == name), None
    )
    if kit_info is None:
        raise KitNotFoundError(name)
    return {
        "name": name,
        "versions": kit_info.versions,
        "latest_version": kit_info.latest_version,
        "source_layer": kit_info.source_layer,
        "applicability": get_applicability(name),
    }


def list_versions(name: str, root: Path | None = None) -> list[str]:
    """
    List a kit's major versions, oldest first.

    :param name: Kit name.
    :param root: When given, list versions in this root only.
    :returns: Version labels, e.g. ``["v1", "v2"]``.
    :raises KitNotFoundError: If the kit does not exist.
    """
    if root is not None:
        _require_kit(name, root=root)
        return list(kits_mod._kit_version_paths(root)[name].keys())
    kit_info = next(
        (k for k in kits_mod.list_all_kits() if k.name == name), None
    )
    if kit_info is None:
        raise KitNotFoundError(name)
    return kit_info.versions


def get_applicability(name: str, root: Path | None = None) -> dict[str, Any]:
    """
    Return the raw stored ``applicability.json`` for a kit.

    :param name: Kit name.
    :param root: When given, read from this root only.
    :returns: The parsed manifest object as stored on disk.
    :raises KitNotFoundError: If the kit (or its manifest) is missing.
    """
    effective_root = root or kits_mod._resolve_kit_root(name)[0]
    manifest_file = kits_mod._manifest_path(effective_root, name)
    if not manifest_file.exists():
        raise KitNotFoundError(name)
    return json.loads(manifest_file.read_text(encoding="utf-8"))


def get_changelog(name: str, root: Path | None = None) -> str:
    """
    Return a kit's raw ``CHANGELOG.md`` text (empty if none on disk).

    :param name: Kit name.
    :param root: When given, read from this root only.
    :returns: Changelog text, or ``""`` if the file is absent.
    :raises KitNotFoundError: If the kit does not exist.
    """
    effective_root = root or kits_mod._resolve_kit_root(name)[0]
    path = writes.resolve_within(effective_root, name, "CHANGELOG.md")
    return path.read_text(encoding="utf-8") if path.exists() else ""


def get_section(
    name: str, version: str, section_id: str, root: Path | None = None
) -> dict[str, Any]:
    """
    Return one section's metadata and body.

    :param name: Kit name.
    :param version: Version label.
    :param section_id: Section id (the file stem).
    :param root: When given, read from this root only (no merging).
    :returns: ``{id, title, gloss, always_load, binding, body}``.
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitSectionNotFoundError: If the section id is unknown.
    """
    outline = kits_mod.read_kit_outline(name, version, root=root)
    meta = next(
        (s for s in outline["sections"] if s["id"] == section_id), None
    )
    body = kits_mod.read_kit(name, version, sections=[section_id], root=root)
    return {
        "id": section_id,
        "title": meta["title"] if meta else section_id,
        "gloss": meta["gloss"] if meta else "",
        "always_load": bool(meta["always_load"]) if meta else False,
        "binding": bool(meta["binding"]) if meta else False,
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
    root: Path | None = None,
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
    :param root: Target root; defaults to the default writable layer.
    :returns: Kit detail (see :func:`get_kit_detail`).
    :raises KitConflictError: If the kit already exists.
    :raises KitValidationError: If the manifest or index is invalid.
    """
    writes.validate_kit_name(name)
    writes.validate_version(version)
    effective_root = root or _kits_write_root()
    kit_dir = writes.resolve_within(effective_root, name)
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

    effective_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=effective_root) as tmp:
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
    return get_kit_detail(name, root=effective_root)


def delete_kit(name: str, root: Path | None = None) -> None:
    """
    Delete a kit and all its versions. Idempotent.

    :param name: Kit name (no error if it does not exist).
    :param root: Target root; defaults to the default writable layer.
    """
    writes.validate_kit_name(name)
    effective_root = root or _kits_write_root()
    kit_dir = writes.resolve_within(effective_root, name)
    writes.remove_path(kit_dir)


def replace_applicability(
    name: str, applicability: dict[str, Any], root: Path | None = None
) -> dict[str, Any]:
    """
    Replace a kit's ``applicability.json`` (idempotent PUT).

    :param name: Kit name (must already exist in the target root).
    :param applicability: New manifest content.
    :param root: Target root; defaults to the default writable layer.
    :returns: The stored manifest.
    :raises KitNotFoundError: If the kit does not exist in the target root.
    :raises KitValidationError: If the manifest is invalid.
    """
    effective_root = root or _kits_write_root()
    _require_kit(name, root=effective_root)
    try:
        kits_mod._validate_manifest(applicability, name)
    except ValueError as exc:
        raise KitValidationError(str(exc)) from exc
    manifest_file = writes.resolve_within(
        effective_root, name, "applicability.json"
    )
    writes.atomic_write_text(
        manifest_file, json.dumps(applicability, indent=2) + "\n"
    )
    return get_applicability(name, root=effective_root)


def create_version(
    name: str,
    version: str,
    summary: str,
    sections: list[SectionInput],
    root: Path | None = None,
) -> list[str]:
    """
    Add a new major version to an existing kit.

    :param name: Kit name (must exist in the target root).
    :param version: New version label, e.g. ``"v2"``.
    :param summary: Version summary.
    :param sections: Sections for the new version (at least one).
    :param root: Target root; defaults to the default writable layer.
    :returns: Updated version list.
    :raises KitNotFoundError: If the kit does not exist.
    :raises KitConflictError: If the version already exists.
    :raises KitValidationError: If the proposed index is invalid.
    """
    effective_root = root or _kits_write_root()
    _require_kit(name, root=effective_root)
    writes.validate_version(version)
    if not sections:
        raise KitValidationError(
            f"Version {version!r} of kit {name!r} must define at least "
            f"one section"
        )
    version_dir = writes.resolve_within(effective_root, name, version)
    if version_dir.exists():
        raise KitConflictError(
            f"Version {version!r} already exists for kit {name!r}"
        )
    kit_dir = writes.resolve_within(effective_root, name)
    with tempfile.TemporaryDirectory(dir=kit_dir) as tmp:
        staging = Path(tmp) / "instructions"
        _populate_instructions(staging, summary, sections)
        _validate_instructions(staging, name)
        version_dir.mkdir(parents=True, exist_ok=True)
        writes.replace_dir(staging, version_dir / "instructions")
    return list_versions(name, root=effective_root)


def delete_version(name: str, version: str, root: Path | None = None) -> list[str]:
    """
    Delete one major version of a kit. Idempotent.

    :param name: Kit name (must exist).
    :param version: Version label to remove (no error if absent).
    :param root: Target root; defaults to the default writable layer.
    :returns: Updated version list.
    :raises KitNotFoundError: If the kit does not exist.
    """
    effective_root = root or _kits_write_root()
    _require_kit(name, root=effective_root)
    writes.validate_version(version)
    version_dir = writes.resolve_within(effective_root, name, version)
    writes.remove_path(version_dir)
    return list_versions(name, root=effective_root)


def _rewrite_instructions(
    name: str,
    version: str,
    transform: Callable[[Path], None],
    root: Path | None = None,
) -> None:
    """
    Apply *transform* to a staged copy of a version's instructions.

    Copies the live ``instructions/`` directory into a staging area,
    lets *transform* mutate it, validates the result, then atomically
    swaps it into place. The live directory is never partially modified.

    When *root* is ``None``, the kit is resolved via the merged catalog
    view and written to its owning layer (raises
    :class:`~app.kits.KitLayerReadonlyError` if that layer is readonly).
    When *root* is given, the kit is resolved and written to that root
    directly (caller is responsible for readonly enforcement).

    :param name: Kit name.
    :param version: Version label.
    :param transform: Callable receiving the staging ``Path`` to mutate.
    :param root: Target root; ``None`` resolves via merged catalog.
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitLayerReadonlyError: If the resolved layer is readonly.
    :raises KitValidationError: If the transformed index is invalid.
    """
    _, index_path = kits_mod._resolve_kit_version(name, version, root=root)
    if root is None:
        settings = kits_mod.get_settings()
        layers = kits_mod._get_effective_layers(settings)
        for layer in layers:
            try:
                index_path.relative_to(layer.path)
            except ValueError:
                continue
            if layer.readonly:
                raise KitLayerReadonlyError(layer.name)
            break
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
    root: Path | None = None,
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
    :param root: Target root; defaults to the kit's owning layer.
    :returns: The stored section (see :func:`get_section`).
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitLayerReadonlyError: If the target layer is readonly.
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

    _rewrite_instructions(name, version, _transform, root=root)
    return get_section(name, version, section_id, root=root)


def delete_section(
    name: str, version: str, section_id: str, root: Path | None = None
) -> list[str]:
    """
    Delete a section from a version. Idempotent for an absent section.

    :param name: Kit name.
    :param version: Version label.
    :param section_id: Section id to remove.
    :param root: Target root; defaults to the kit's owning layer.
    :returns: Remaining section ids in document order.
    :raises KitNotFoundError / KitVersionNotFoundError: If unresolved.
    :raises KitLayerReadonlyError: If the target layer is readonly.
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

    _rewrite_instructions(name, version, _transform, root=root)
    outline = kits_mod.read_kit_outline(name, version, root=root)
    return [s["id"] for s in outline["sections"]]
