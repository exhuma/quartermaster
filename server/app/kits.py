"""
Kit discovery and content access.

Kits are versioned: major versions live in subfolders
``kits/<name>/v<N>/``.  Each version folder must contain an
``instructions/`` directory holding an ``index.toml`` manifest plus one
Markdown file per logical section.  A ``CHANGELOG.md`` at
``kits/<name>/CHANGELOG.md`` tracks all version history and is used
to summarise changes between versions.
"""

from __future__ import annotations

import json
import logging
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import KitLayerConfig, get_settings
from app.identity import current_sub
from app.private_kits import owned_private_roots

logger = logging.getLogger(__name__)


class KitNotFoundError(Exception):
    """
    Raised when a requested kit name does not match any known kit.

    :param name: The kit name that was requested.
    """

    def __init__(self, name: str) -> None:
        """
        Initialise the error with the missing kit name.

        :param name: Requested kit name.
        """
        super().__init__(f"Kit not found: {name!r}")
        self.name = name


class KitVersionNotFoundError(Exception):
    """
    Raised when a requested version does not exist for a kit.

    :param name: The kit name.
    :param version: The requested version string, e.g. ``"v1"``.
    """

    def __init__(self, name: str, version: str) -> None:
        """
        Initialise the error with the kit name and missing version.

        :param name: Kit name.
        :param version: Requested version string.
        """
        super().__init__(
            f"Version {version!r} not found for kit {name!r}"
        )
        self.name = name
        self.version = version


class KitSectionNotFoundError(Exception):
    """
    Raised when a requested section id does not exist in a kit index.

    :param name: The kit name.
    :param unknown: The section ids that could not be resolved.
    :param valid: The valid section ids available for the kit.
    """

    def __init__(
        self, name: str, unknown: list[str], valid: list[str]
    ) -> None:
        """
        Initialise the error with the kit name and section ids.

        :param name: Kit name.
        :param unknown: Section ids that were requested but not found.
        :param valid: Section ids that are available for the kit.
        """
        super().__init__(
            f"Unknown section(s) {unknown!r} for kit {name!r}; "
            f"valid sections: {valid!r}"
        )
        self.name = name
        self.unknown = unknown
        self.valid = valid


class KitConflictError(Exception):
    """
    Raised when a write would collide with existing content.

    For example: creating a kit whose directory already exists, or
    creating a version that is already present.

    :param message: Human-readable description of the collision.
    """

    def __init__(self, message: str) -> None:
        """
        Initialise the error with a description.

        :param message: Description of the collision.
        """
        super().__init__(message)


class KitValidationError(Exception):
    """
    Raised when a proposed write would produce invalid kit content.

    The write is rejected before any bytes are committed, so the
    on-disk catalog is never left in a state that fails to load.

    :param message: Human-readable validation failure description.
    """

    def __init__(self, message: str) -> None:
        """
        Initialise the error with a description.

        :param message: Validation failure description.
        """
        super().__init__(message)


class KitLayerNotFoundError(Exception):
    """
    Raised when a requested layer identifier is not configured.

    :param layer_name: The layer name that was requested.
    """

    def __init__(self, layer_name: str) -> None:
        super().__init__(f"Kit layer not found: {layer_name!r}")
        self.layer_name = layer_name


class KitLayerReadonlyError(Exception):
    """
    Raised when a write is attempted on a read-only layer.

    :param layer_name: The layer name that is read-only.
    """

    def __init__(self, layer_name: str) -> None:
        super().__init__(f"Kit layer {layer_name!r} is read-only")
        self.layer_name = layer_name


@dataclass(frozen=True)
class KitInfo:
    """
    Lightweight metadata for a single instruction kit.

    :param name: Directory name under the kits root.
    :param description: ``summary`` from the latest version's
        ``instructions/index.toml``, used as a brief summary.
    :param versions: Sorted list of available major version strings,
        e.g. ``["v1", "v2"]``, from oldest to newest.
    :param latest_version: The highest available major version string.
    :param source_layer: Name of the layer that owns this kit (the
        highest-priority layer containing it). ``None`` in legacy
        single-root usage.
    :param broken: True when the kit's ``instructions/index.toml`` is missing
        or malformed. A broken kit is still listed (so it can be surfaced and
        fixed) but is excluded from selection/serving.
    :param error: Human-readable reason the kit is broken, or ``None``.
    """

    name: str
    description: str
    versions: list[str]
    latest_version: str
    source_layer: str | None = None
    broken: bool = False
    error: str | None = None


@dataclass(frozen=True)
class KitSection:
    """
    A single section of a kit's instructions.

    :param id: Stable identifier (the section file's stem), used to
        request the section via :func:`read_kit`.
    :param file: Section file basename within the ``instructions/``
        directory, e.g. ``"invariant.md"``.
    :param title: Human-readable section title.
    :param gloss: One-line summary shown in the outline.
    :param always_load: Whether this section holds core invariants that
        an agent should always pull into context.
    :param binding: When ``true``, this section cannot be overridden by
        a higher-priority overlay layer.  A binding section in a
        lower-priority (base) layer is always contributed to the merged
        kit, even when an overlay kit shadows the same kit name.
        Relevant only in multi-root layered setups; has no effect in
        single-root deployments.
    """

    id: str
    file: str
    title: str
    gloss: str
    always_load: bool
    binding: bool = False


@dataclass(frozen=True)
class KitIndex:
    """
    Parsed ``instructions/index.toml`` manifest for one kit version.

    :param summary: Brief kit description.
    :param sections: Ordered sections; document order is list order.
    """

    summary: str
    sections: list[KitSection]


@dataclass(frozen=True)
class KitApplicability:
    """
    Structured applicability metadata for V2 kit discovery.

    :param kit_type: One of ``module``, ``stack``, ``release``.
    :param summary: Short, compact applicability description.
    :param domains: Normalized problem domains this kit targets.
    :param languages: Languages commonly associated with this kit.
    :param frameworks: Frameworks commonly associated with this kit.
    :param contexts: Project contexts where this kit is useful.
    :param requires: Hard requirements per trait category.
    :param excludes: Hard exclusion constraints per trait category.
    :param optional_signals: Additional weak signals for ranking.
    :param related_kits: Kit names frequently used together.
    :param priority: Base ranking priority (higher means preferred).
    """

    kit_type: str
    summary: str
    domains: list[str]
    languages: list[str]
    frameworks: list[str]
    contexts: list[str]
    requires: dict[str, list[str]]
    excludes: dict[str, list[str]]
    optional_signals: list[str]
    related_kits: list[str]
    priority: int


@dataclass(frozen=True)
class ProjectTraits:
    """Normalized project traits used by the V2 selector."""

    languages: list[str]
    frameworks: list[str]
    capabilities: list[str]
    contexts: list[str]


_TRAIT_KEYS = ("languages", "frameworks", "capabilities", "contexts")
_KIT_TYPES = {"module", "stack", "release"}


# ---------------------------------------------------------------------------
# V2 selector scoring model
# ---------------------------------------------------------------------------
#
# A candidate's score starts at the kit's declared ``priority`` and accrues a
# fixed weight for every project trait dimension that overlaps the kit. The
# weights are ordered by how strongly each dimension predicts a good fit: a
# shared *language* is the strongest signal, *frameworks* next, capability /
# domain signals weaker, and *contexts* weakest. A satisfied hard ``requires``
# constraint is also a strong positive signal. Hard constraints still gate
# eligibility independently: any ``excludes`` overlap or unmet ``requires``
# makes a candidate ineligible, and a required-but-unprovided trait makes it
# uncertain. Keeping these as named constants (rather than inline literals)
# documents the model and keeps tuning in one place.
WEIGHT_LANGUAGES = 24
WEIGHT_FRAMEWORKS = 22
WEIGHT_CAPABILITIES = 16  # domains + optional_signals (see _evaluate_candidate)
WEIGHT_CONTEXTS = 10
WEIGHT_REQUIRE_SATISFIED = 18

WEIGHT_BY_DIMENSION = {
    "languages": WEIGHT_LANGUAGES,
    "frameworks": WEIGHT_FRAMEWORKS,
    "capabilities": WEIGHT_CAPABILITIES,
    "contexts": WEIGHT_CONTEXTS,
}

# Per-candidate confidence thresholds (used in ``_evaluate_candidate``).
CANDIDATE_HIGH_SCORE = 75  # eligible, no uncertainty, score >= this -> "high"
CANDIDATE_UNCERTAIN_MEDIUM = 55  # uncertain but score >= this -> "medium"

# Aggregate selection thresholds (used in ``select_kits_v2``).
SELECT_THRESHOLD_DEFAULT = 60
SELECT_THRESHOLD_BROADEN = 40
SELECT_HIGH_SCORE = 80
SELECT_HIGH_COVERAGE = 0.75
SELECT_MEDIUM_SCORE = 60
SELECT_MEDIUM_COVERAGE = 0.4
BROADEN_COVERAGE_FLOOR = 0.5


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _version_key(v: str) -> int:
    """
    Return the numeric part of a major-version string for sorting.

    E.g. ``"v3"`` → ``3``.  Non-matching strings return ``0``.

    :param v: Version string, expected to match ``v<N>``.
    :returns: Integer sort key.
    """
    m = re.fullmatch(r"v(\d+)", v)
    return int(m.group(1)) if m else 0


def _normalize_values(values: list[str]) -> list[str]:
    """
    Normalize a list of trait labels to stable lowercase tokens.

    :param values: Raw trait values.
    :returns: Unique lowercase values preserving first-seen order.
    """
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        norm = value.strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        result.append(norm)
    return result


def _coerce_str_list(raw: Any, *, field_name: str) -> list[str]:
    """
    Validate and normalize a string list field from manifest JSON.

    :param raw: Raw field value.
    :param field_name: Field name for error reporting.
    :returns: Normalized list of lowercase string values.
    :raises ValueError: If the field is not a list of strings.
    """
    if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
        raise ValueError(f"Manifest field {field_name!r} must be a list[str]")
    return _normalize_values(raw)


def _manifest_path(root: Path, kit_name: str) -> Path:
    """
    Return the expected manifest path for a kit.

    :param root: Kits root path.
    :param kit_name: Kit directory name.
    :returns: Path to ``applicability.json``.
    """
    return root / kit_name / "applicability.json"


def _load_manifest(root: Path, kit_name: str) -> KitApplicability:
    """
    Load and validate a kit applicability manifest.

    :param root: Kits root path.
    :param kit_name: Kit directory name.
    :returns: Parsed and normalized applicability metadata.
    :raises FileNotFoundError: If manifest file is missing.
    :raises ValueError: If manifest schema is invalid.
    """
    manifest_file = _manifest_path(root, kit_name)
    if not manifest_file.exists():
        raise FileNotFoundError(
            f"Missing applicability manifest for kit {kit_name!r}: "
            f"{manifest_file}"
        )
    raw = json.loads(manifest_file.read_text(encoding="utf-8"))
    return _validate_manifest(raw, kit_name)


def _validate_manifest(raw: Any, kit_name: str) -> KitApplicability:
    """
    Validate and normalize an in-memory applicability manifest.

    This is the schema check shared by :func:`_load_manifest` (which
    reads the manifest from disk) and the write path (which validates a
    proposed manifest *before* committing it), so both enforce exactly
    the same rules.

    :param raw: Parsed manifest object (e.g. from ``json.loads`` or a
        request body).
    :param kit_name: Kit directory name (for error messages).
    :returns: Parsed and normalized applicability metadata.
    :raises ValueError: If the manifest schema is invalid.
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Manifest for kit {kit_name!r} must be a JSON object")

    required_fields = {
        "kit_type",
        "summary",
        "domains",
        "languages",
        "frameworks",
        "contexts",
        "requires",
        "excludes",
        "optional_signals",
        "related_kits",
        "priority",
    }
    missing = sorted(required_fields.difference(raw.keys()))
    if missing:
        raise ValueError(
            f"Manifest for kit {kit_name!r} missing fields: {missing}"
        )

    kit_type = str(raw["kit_type"]).strip().lower()
    if kit_type not in _KIT_TYPES:
        raise ValueError(
            f"Manifest for kit {kit_name!r} has invalid kit_type {kit_type!r}"
        )
    summary = str(raw["summary"]).strip()
    if not summary:
        raise ValueError(f"Manifest for kit {kit_name!r} has empty summary")

    def _validate_constraints(name: str) -> dict[str, list[str]]:
        value = raw[name]
        if not isinstance(value, dict):
            raise ValueError(f"Manifest field {name!r} must be an object")
        result: dict[str, list[str]] = {}
        for key in _TRAIT_KEYS:
            if key not in value:
                raise ValueError(
                    f"Manifest field {name!r} for kit {kit_name!r} "
                    f"must include key {key!r}"
                )
            result[key] = _coerce_str_list(
                value[key], field_name=f"{name}.{key}"
            )
        return result

    priority = raw["priority"]
    if not isinstance(priority, int):
        raise ValueError(
            f"Manifest field 'priority' for kit {kit_name!r} must be int"
        )

    return KitApplicability(
        kit_type=kit_type,
        summary=summary,
        domains=_coerce_str_list(raw["domains"], field_name="domains"),
        languages=_coerce_str_list(raw["languages"], field_name="languages"),
        frameworks=_coerce_str_list(raw["frameworks"], field_name="frameworks"),
        contexts=_coerce_str_list(raw["contexts"], field_name="contexts"),
        requires=_validate_constraints("requires"),
        excludes=_validate_constraints("excludes"),
        optional_signals=_coerce_str_list(
            raw["optional_signals"], field_name="optional_signals"
        ),
        related_kits=_coerce_str_list(
            raw["related_kits"], field_name="related_kits"
        ),
        priority=priority,
    )


def _load_kit_index(index_path: Path, kit_name: str) -> KitIndex:
    """
    Load and validate a kit's ``instructions/index.toml`` manifest.

    :param index_path: Path to the ``index.toml`` file.
    :param kit_name: Kit directory name (for error messages).
    :returns: Parsed index with an ordered section list.
    :raises ValueError: If the manifest is malformed or a referenced
        section file is missing.
    """
    try:
        raw = tomllib.loads(index_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Index for kit {kit_name!r} is not valid TOML: {exc}"
        ) from exc

    summary = str(raw.get("summary", "")).strip()
    if not summary:
        raise ValueError(f"Index for kit {kit_name!r} has empty summary")

    raw_sections = raw.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise ValueError(
            f"Index for kit {kit_name!r} must define a non-empty "
            f"'sections' array"
        )

    instr_dir = index_path.parent
    sections: list[KitSection] = []
    seen_ids: set[str] = set()
    for pos, entry in enumerate(raw_sections):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Index for kit {kit_name!r}: section #{pos} must be a table"
            )
        file = str(entry.get("file", "")).strip()
        if not file or "/" in file or "\\" in file:
            raise ValueError(
                f"Index for kit {kit_name!r}: section #{pos} has an "
                f"invalid 'file': {file!r}"
            )
        if not (instr_dir / file).is_file():
            raise ValueError(
                f"Index for kit {kit_name!r}: section file {file!r} "
                f"does not exist"
            )
        title = str(entry.get("title", "")).strip()
        if not title:
            raise ValueError(
                f"Index for kit {kit_name!r}: section {file!r} has an "
                f"empty 'title'"
            )
        always_load = entry.get("always_load", False)
        if not isinstance(always_load, bool):
            raise ValueError(
                f"Index for kit {kit_name!r}: section {file!r} field "
                f"'always_load' must be a boolean"
            )
        binding = entry.get("binding", False)
        if not isinstance(binding, bool):
            raise ValueError(
                f"Index for kit {kit_name!r}: section {file!r} field "
                f"'binding' must be a boolean"
            )
        section_id = Path(file).stem
        if section_id in seen_ids:
            raise ValueError(
                f"Index for kit {kit_name!r}: duplicate section id "
                f"{section_id!r}"
            )
        seen_ids.add(section_id)
        sections.append(
            KitSection(
                id=section_id,
                file=file,
                title=title,
                gloss=str(entry.get("gloss", "")).strip(),
                always_load=always_load,
                binding=binding,
            )
        )

    return KitIndex(summary=summary, sections=sections)


def _kit_version_paths(root: Path) -> dict[str, dict[str, Path]]:
    """
    Scan *root* for versioned kit instruction manifests.

    A kit is any subdirectory at the root level that contains a path
    matching ``<name>/v<N>/instructions/index.toml`` where ``N`` is a
    positive integer.

    :param root: Repository kits root directory to scan.
    :returns: Mapping of kit name → ``{version_string: index_path}``,
        with versions sorted in ascending numeric order.
    """
    result: dict[str, dict[str, Path]] = {}
    for p in sorted(root.glob("*/v*/instructions/index.toml")):
        # p = <root>/<kit-name>/v<N>/instructions/index.toml
        version = p.parent.parent.name   # v<N>
        if not re.fullmatch(r"v\d+", version):
            continue
        kit_name = p.parent.parent.parent.name   # <kit-name>
        result.setdefault(kit_name, {})[version] = p
    return {
        name: dict(
            sorted(
                versions.items(),
                key=lambda kv: _version_key(kv[0]),
            )
        )
        for name, versions in sorted(result.items())
    }


def _get_effective_layers(settings: Any) -> list[KitLayerConfig]:
    """
    Return effective layers from a Settings-like object.

    Handles both the real :class:`~app.config.Settings` (which has
    ``effective_layers``) and the minimal mocks used in tests (which
    only have ``kits_root``).

    :param settings: Any object that has ``effective_layers`` or
        ``kits_root``.
    :returns: Non-empty list of :class:`KitLayerConfig`.
    """
    if hasattr(settings, "effective_layers"):
        return settings.effective_layers
    root = getattr(settings, "kits_root", None)
    if root is not None:
        return [KitLayerConfig(name="default", path=Path(root), readonly=False)]
    raise ValueError("Settings object has no kit root configured")


# The synthetic layer name for a caller's private-kit overlay. One private
# layer at most per caller, placed at highest priority so a private kit shadows
# a public kit of the same name FOR THE OWNER ONLY.
_PRIVATE_LAYER_NAME = "__private__"

# Sentinel distinguishing "resolve the subject from the identity contextvar"
# (the default for owner-aware reads) from an explicit ``None`` meaning
# "public catalog only, ignore any caller in context" (used by the vocabulary
# / embedding-cache path so private kits never poison the shared cache).
_CTX_SUBJECT: Any = object()


def _resolve_subject(subject: Any) -> str | None:
    """Resolve a subject argument to a concrete subject or ``None``.

    :param subject: ``_CTX_SUBJECT`` → read the identity contextvar; otherwise
        a ``str`` subject or ``None`` (public) passed straight through.
    """
    if subject is _CTX_SUBJECT:
        return current_sub()
    return subject


def _caller_layers(subject: Any = _CTX_SUBJECT) -> list[KitLayerConfig]:
    """Return the effective layers for a caller, private overlay last.

    The public layers are always present; when the caller (from *subject* or
    the identity contextvar) has an existing private catalog, it is appended as
    the highest-priority layer. A caller with no private kits — or no
    identity — sees exactly the public catalog, so this is a no-op on the hot
    public path and default-deny for private content.

    :param subject: ``_CTX_SUBJECT`` (contextvar), a ``str`` subject, or
        ``None`` to force public-only.
    :returns: Ordered layers, base → overlay, private overlay last if any.
    """
    settings = get_settings()
    layers = list(_get_effective_layers(settings))
    sub = _resolve_subject(subject)
    for root in owned_private_roots(sub):
        layers.append(
            KitLayerConfig(
                name=_PRIVATE_LAYER_NAME, path=root, readonly=False
            )
        )
    return layers


def _kit_version_paths_layered(
    layers: list[KitLayerConfig],
) -> dict[str, dict[str, tuple[Path, Path, str]]]:
    """
    Scan multiple kit layers and merge with kit-level shadowing.

    Iterates *layers* from lowest to highest priority.  When the same
    kit name appears in multiple layers, the highest-priority layer that
    contains it owns **all** its versions (kit-level shadowing).

    :param layers: Ordered list of layers, base (index 0) → overlay
        (last).
    :returns: Mapping of kit name → ``{version: (index_path,
        layer_root, layer_name)}``, versions sorted oldest → newest.
    """
    merged: dict[str, tuple[dict[str, Path], Path, str]] = {}
    for layer in layers:
        layer_paths = _kit_version_paths(layer.path)
        for kit_name, versions in layer_paths.items():
            merged[kit_name] = (versions, layer.path, layer.name)

    result: dict[str, dict[str, tuple[Path, Path, str]]] = {}
    for kit_name in sorted(merged.keys()):
        versions, layer_root, layer_name = merged[kit_name]
        result[kit_name] = {
            version: (index_path, layer_root, layer_name)
            for version, index_path in sorted(
                versions.items(), key=lambda kv: _version_key(kv[0])
            )
        }
    return result


def _resolve_kit_root(
    name: str, subject: Any = _CTX_SUBJECT
) -> tuple[Path, str]:
    """
    Return the root and layer name for the highest-priority layer
    containing *name*.

    :param name: Kit name.
    :param subject: Caller identity for private-kit visibility (see
        :func:`_caller_layers`).
    :returns: Tuple of ``(root_path, layer_name)``.
    :raises KitNotFoundError: If no configured layer contains *name*.
    """
    layers = _caller_layers(subject)
    for layer in reversed(layers):
        if name in _kit_version_paths(layer.path):
            return layer.path, layer.name
    raise KitNotFoundError(name)


def _resolve_merged_kit(
    name: str, version: str | None = None, subject: Any = _CTX_SUBJECT
) -> tuple[str, Path, list[tuple[KitSection, Path]]]:
    """
    Resolve a kit for a merged read, collecting binding section contributions.

    Finds the primary (overlay) layer for *name* and then walks
    lower-priority layers to collect sections whose ``binding=true``
    attribute means they survive shadowing.

    :param name: Kit name.
    :param version: Major version string; defaults to latest.
    :returns: Tuple of ``(resolved_version, primary_index_path,
        binding_contributions)`` where *binding_contributions* is a list
        of ``(KitSection, instr_dir)`` pairs from lower-priority layers.
    :raises KitNotFoundError: If no layer has the kit.
    :raises KitVersionNotFoundError: If the version does not exist in
        the primary layer.
    """
    layers = _caller_layers(subject)
    layered = _kit_version_paths_layered(layers)

    if name not in layered:
        raise KitNotFoundError(name)

    kit_versions = layered[name]
    resolved = version or max(kit_versions, key=_version_key)
    if resolved not in kit_versions:
        raise KitVersionNotFoundError(name, resolved)

    primary_index_path, _primary_root, primary_layer_name = kit_versions[
        resolved
    ]

    # Collect binding sections from lower-priority layers
    binding_contributions: list[tuple[KitSection, Path]] = []
    for layer in layers:
        if layer.name == primary_layer_name:
            break
        lower_versions = _kit_version_paths(layer.path)
        if name in lower_versions and resolved in lower_versions[name]:
            lower_index_path = lower_versions[name][resolved]
            lower_index = _load_kit_index(lower_index_path, name)
            lower_instr_dir = lower_index_path.parent
            for section in lower_index.sections:
                if section.binding:
                    binding_contributions.append((section, lower_instr_dir))

    return resolved, primary_index_path, binding_contributions


def _parse_version_tuple(v: str) -> tuple[int, ...]:
    """
    Parse a version label into a comparable integer tuple.

    Accepts labels like ``"v1"``, ``"v1.2"``, ``"v1.2.3"``.

    :param v: Version string, optionally prefixed with ``"v"``.
    :returns: Tuple of integers, e.g. ``(1, 2, 3)``.
    """
    stripped = v.lstrip("v")
    parts = re.split(r"[.\-]", stripped)
    result: list[int] = []
    for part in parts:
        try:
            result.append(int(part))
        except ValueError:
            result.append(0)
    return tuple(result)


def _parse_changelog(content: str) -> dict[str, str]:
    """
    Parse a ``CHANGELOG.md`` into a mapping of version → section text.

    Version headings must match ``## v<version>`` (optionally followed
    by a title after the version), e.g.
    ``## v1.2.0 — Feature additions``.

    :param content: Full Markdown text of the changelog.
    :returns: Ordered mapping of version label (e.g. ``"v1.0.0"``)
        to the body text of that section, in document order.
    """
    result: dict[str, str] = {}
    current_version: str | None = None
    current_lines: list[str] = []
    for line in content.splitlines(keepends=True):
        # e.g. ## v1.2.0 or ## v2.0.0-rc1
        m = re.match(r"^## (v[\w.+-]+)", line)
        if m:
            if current_version is not None:
                result[current_version] = "".join(
                    current_lines
                ).strip()
            current_version = m.group(1)
            current_lines = []
        elif current_version is not None:
            current_lines.append(line)
    if current_version is not None:
        result[current_version] = "".join(current_lines).strip()
    return result


# Keywords that indicate an end-user-facing change (authentication,
# API shape, user flows, data model, etc.). Each entry is a deliberate whole
# word matched on word boundaries; ``user-facing`` is matched explicitly with
# a space-or-hyphen separator rather than a wildcard so it cannot match
# unrelated runs like "userXfacing".
_USER_FACING_RE = re.compile(
    r"\b("
    r"authentication|authorisation|authorization"
    r"|api|endpoint|endpoints|url|urls|route|routes"
    r"|password|passwords|token|tokens|session|sessions"
    r"|login|logout|signup|register"
    r"|breaking|interface"
    r"|schema|migration|migrations|database"
    r")\b"
    r"|\buser[ -]facing\b",
    re.IGNORECASE,
)


def _normalize_traits(
    *,
    languages: list[str] | None,
    frameworks: list[str] | None,
    capabilities: list[str] | None,
    contexts: list[str] | None,
) -> ProjectTraits:
    """Build normalized project traits from selector input lists."""
    return ProjectTraits(
        languages=_normalize_values(languages or []),
        frameworks=_normalize_values(frameworks or []),
        capabilities=_normalize_values(capabilities or []),
        contexts=_normalize_values(contexts or []),
    )


def _catalog_entries(
    *, strict: bool = False, subject: Any = _CTX_SUBJECT
) -> tuple[list[tuple[KitInfo, KitApplicability]], list[dict[str, str]]]:
    """
    Return all kits with validated applicability metadata.

    A kit whose ``applicability.json`` is missing or malformed is skipped
    and recorded as a warning rather than aborting the whole catalog, so a
    single bad manifest does not take down discovery for every other kit.
    In multi-root setups, the kit is loaded from its owning (highest-
    priority) layer.

    :param strict: When true, re-raise the first manifest error instead of
        skipping it. Useful for CI/tests that want fail-fast validation.
    :returns: A tuple ``(entries, warnings)`` where ``entries`` is a list of
        ``(KitInfo, KitApplicability)`` tuples sorted by kit name, and
        ``warnings`` is a list of ``{"kit": name, "error": message}`` dicts
        for every kit whose manifest could not be loaded.
    """
    entries: list[tuple[KitInfo, KitApplicability]] = []
    warnings: list[dict[str, str]] = []
    layers = _caller_layers(subject)
    layer_by_name = {layer.name: layer for layer in layers}
    for info in list_all_kits(subject=subject):
        # A kit with a broken index cannot be served, so it must never be
        # offered to the selector/resolver — record it and skip.
        if info.broken:
            if strict:
                raise ValueError(
                    f"kit {info.name!r} has an invalid index: {info.error}"
                )
            warnings.append({
                "kit": info.name,
                "error": info.error or "invalid kit index",
            })
            continue
        # Resolve the kit's owning layer root from the source_layer tag
        layer = layer_by_name.get(info.source_layer or "")
        if layer is None:
            # Fallback for legacy single-root mocks without source_layer
            try:
                root, _ = _resolve_kit_root(info.name, subject=subject)
            except KitNotFoundError:
                warnings.append({
                    "kit": info.name,
                    "error": "could not resolve kit layer",
                })
                continue
        else:
            root = layer.path
        try:
            applicability = _load_manifest(root, info.name)
        except (ValueError, FileNotFoundError, OSError) as exc:
            if strict:
                raise
            logger.warning("skipping kit %r: %s", info.name, exc)
            warnings.append({"kit": info.name, "error": str(exc)})
            continue
        entries.append((info, applicability))
    return entries, warnings


def _evaluate_candidate(
    kit: KitInfo,
    applicability: KitApplicability,
    traits: ProjectTraits,
) -> dict[str, Any]:
    """
    Evaluate one kit against project traits for selector ranking.

    :param kit: Kit metadata.
    :param applicability: Structured applicability manifest.
    :param traits: Normalized project traits.
    :returns: Candidate score and diagnostics.
    """
    reasons: list[str] = []
    score = applicability.priority
    uncertain = False
    ineligible = False
    matched_dimensions: set[str] = set()

    provided = {
        "languages": set(traits.languages),
        "frameworks": set(traits.frameworks),
        "capabilities": set(traits.capabilities),
        "contexts": set(traits.contexts),
    }
    known = {
        "languages": set(applicability.languages),
        "frameworks": set(applicability.frameworks),
        # Capabilities are matched against the union of declared problem
        # ``domains`` and weak ``optional_signals``. Both describe "what the
        # kit is good at"; the selector intentionally pools them rather than
        # distinguishing a primary domain from a weak hint at match time.
        "capabilities": (
            set(applicability.domains)
            | set(applicability.optional_signals)
        ),
        "contexts": set(applicability.contexts),
    }

    for key in _TRAIT_KEYS:
        overlap = provided[key].intersection(known[key])
        if overlap:
            matched_dimensions.add(key)
            reasons.append(f"match:{key}")
            score += WEIGHT_BY_DIMENSION[key]

    for key in _TRAIT_KEYS:
        excluded = provided[key].intersection(set(applicability.excludes[key]))
        if excluded:
            ineligible = True
            reasons.append(f"exclude:{key}")

    for key in _TRAIT_KEYS:
        required = set(applicability.requires[key])
        if not required:
            continue
        if provided[key]:
            if provided[key].intersection(required):
                score += WEIGHT_REQUIRE_SATISFIED
                matched_dimensions.add(key)
                reasons.append(f"require-ok:{key}")
            else:
                ineligible = True
                reasons.append(f"require-miss:{key}")
        else:
            uncertain = True
            reasons.append(f"need-trait:{key}")

    if ineligible:
        confidence = "low"
    elif uncertain:
        confidence = "medium" if score >= CANDIDATE_UNCERTAIN_MEDIUM else "low"
    else:
        confidence = "high" if score >= CANDIDATE_HIGH_SCORE else "medium"

    return {
        "name": kit.name,
        "latest_version": kit.latest_version,
        "kit_type": applicability.kit_type,
        "score": score,
        "confidence": confidence,
        "ineligible": ineligible,
        "uncertain": uncertain,
        "reasons": reasons,
        "summary": applicability.summary,
        "matched_dimensions": sorted(matched_dimensions),
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def iter_catalog() -> list[tuple[KitInfo, KitApplicability]]:
    """
    Return all kits paired with their validated applicability metadata.

    This is the public, additive accessor over :func:`_catalog_entries`
    used by the server-side inference layer (``app.traits``) to derive
    the trait vocabulary and per-trait pseudo-documents. Kits whose
    manifest is missing or malformed are skipped (the same lenient
    behaviour as the V2 selector), so a single bad manifest never aborts
    discovery.

    :returns: List of ``(KitInfo, KitApplicability)`` tuples sorted by
        kit name.
    """
    # Public catalog only: this feeds the trait vocabulary and the shared,
    # on-disk embedding cache, which must never contain per-caller private
    # kits (see app.traits / app.embeddings).
    entries, _warnings = _catalog_entries(subject=None)
    return entries


def list_all_kits(subject: Any = _CTX_SUBJECT) -> list[KitInfo]:
    """
    Return metadata for all available instruction kits (merged view).

    In a multi-root setup, kit names present in multiple layers are
    represented once, from the highest-priority (overlay) layer. The caller's
    own private kits (if any) are merged in as the highest-priority overlay;
    no other caller's private kits are ever visible.

    :param subject: Caller identity for private-kit visibility (see
        :func:`_caller_layers`).
    :returns: List of :class:`KitInfo` instances sorted alphabetically
        by kit name, each including available versions and the latest.
    """
    layers = _caller_layers(subject)
    logger.debug(
        "list_all_kits: scanning %d layer(s): %s",
        len(layers),
        [layer.name for layer in layers],
    )
    kits: list[KitInfo] = []
    for name, versions_with_src in _kit_version_paths_layered(layers).items():
        latest = max(versions_with_src, key=_version_key)
        index_path, _layer_root, layer_name = versions_with_src[latest]
        # A single malformed kit must not abort the whole catalog: flag it as
        # broken (with the reason) and keep going, mirroring the resilience
        # pattern in ``_catalog_entries``. Version/name/layer come from the path
        # scan, so a broken kit still lists its versions.
        try:
            index = _load_kit_index(index_path, name)
            kits.append(
                KitInfo(
                    name=name,
                    description=index.summary,
                    versions=list(versions_with_src.keys()),
                    latest_version=latest,
                    source_layer=layer_name,
                )
            )
        except (ValueError, OSError) as exc:
            logger.warning("kit %r has an invalid index: %s", name, exc)
            kits.append(
                KitInfo(
                    name=name,
                    description="",
                    versions=list(versions_with_src.keys()),
                    latest_version=latest,
                    source_layer=layer_name,
                    broken=True,
                    error=str(exc),
                )
            )
    return kits


def list_private_kits(subject: str) -> list[KitInfo]:
    """
    Return only the private kits owned by *subject* (never public kits).

    Powers the owner's private-kit management view. Returns an empty list for
    an owner with no private catalog.

    :param subject: The owner's stable subject.
    :returns: The owner's private :class:`KitInfo` entries, sorted by name.
    """
    if not subject:
        return []
    return [
        kit
        for kit in list_all_kits(subject=subject)
        if kit.source_layer == _PRIVATE_LAYER_NAME
    ]


def list_catalog_v2() -> list[dict[str, Any]]:
    """
    Return compact V2 applicability metadata for all kits.

    This endpoint is intentionally terse and optimized for candidate
    narrowing before loading full kit content.

    :returns: List of compact kit metadata objects.
    """
    entries, _warnings = _catalog_entries()
    catalog: list[dict[str, Any]] = []
    for info, applicability in entries:
        catalog.append(
            {
                "name": info.name,
                "latest_version": info.latest_version,
                "kit_type": applicability.kit_type,
                "summary": applicability.summary,
                "top_signals": applicability.optional_signals[:3],
                "requires": {
                    k: v for k, v in applicability.requires.items() if v
                },
                "excludes": {
                    k: v for k, v in applicability.excludes.items() if v
                },
            }
        )
    return catalog


def list_available_traits_v2() -> dict[str, Any]:
    """
    Return normalized trait vocabularies observed across all kit manifests.

    This allows clients to discover valid trait labels for
    ``select_kits_v2`` and identify unknown traits that may require
    kit extensions.

    :returns: Dict containing aggregated, sorted trait vocabularies.
    """
    trait_keys = ["languages", "frameworks", "capabilities", "contexts"]
    kit_types: set[str] = set()
    languages: set[str] = set()
    frameworks: set[str] = set()
    capabilities: set[str] = set()
    contexts: set[str] = set()
    domains: set[str] = set()
    optional_signals: set[str] = set()

    entries, warnings = _catalog_entries()
    for _, applicability in entries:
        kit_types.add(applicability.kit_type)
        domains.update(applicability.domains)
        optional_signals.update(applicability.optional_signals)
        capabilities.update(applicability.domains)
        capabilities.update(applicability.optional_signals)

        languages.update(applicability.languages)
        languages.update(applicability.requires["languages"])
        languages.update(applicability.excludes["languages"])

        frameworks.update(applicability.frameworks)
        frameworks.update(applicability.requires["frameworks"])
        frameworks.update(applicability.excludes["frameworks"])

        contexts.update(applicability.contexts)
        contexts.update(applicability.requires["contexts"])
        contexts.update(applicability.excludes["contexts"])

        capabilities.update(applicability.requires["capabilities"])
        capabilities.update(applicability.excludes["capabilities"])

    return {
        "trait_keys": trait_keys,
        "kit_types": sorted(kit_types),
        "languages": sorted(languages),
        "frameworks": sorted(frameworks),
        "capabilities": sorted(capabilities),
        "contexts": sorted(contexts),
        "domains": sorted(domains),
        "optional_signals": sorted(optional_signals),
        "warnings": warnings,
    }


def select_kits_v2(
    *,
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    capabilities: list[str] | None = None,
    contexts: list[str] | None = None,
    broaden: bool = False,
    limit: int = 8,
) -> dict[str, Any]:
    """
    Rank candidate kits from structured project traits.

    :param languages: Project language hints, e.g. ``["python"]``.
    :param frameworks: Framework hints, e.g. ``["fastapi"]``.
    :param capabilities: Capability hints, e.g. ``["auth", "rest-api"]``.
    :param contexts: Context hints, e.g. ``["docs", "hosting"]``.
    :param broaden: When true, lower the score threshold to widen recall.
    :param limit: Max number of candidates to return.
    :returns: Ranked candidates and selection diagnostics.
    """
    traits = _normalize_traits(
        languages=languages,
        frameworks=frameworks,
        capabilities=capabilities,
        contexts=contexts,
    )
    max_items = max(1, min(limit, 30))

    entries, warnings = _catalog_entries()
    evaluated = [
        _evaluate_candidate(info, applicability, traits)
        for info, applicability in entries
    ]
    eligible = [c for c in evaluated if not c["ineligible"]]
    eligible.sort(key=lambda c: (-c["score"], c["name"]))

    threshold = (
        SELECT_THRESHOLD_BROADEN if broaden else SELECT_THRESHOLD_DEFAULT
    )
    selected = [c for c in eligible if c["score"] >= threshold]

    if not selected and eligible:
        selected = eligible[:max_items]

    selected = selected[:max_items]
    provided_dimensions = [
        key
        for key, values in {
            "languages": traits.languages,
            "frameworks": traits.frameworks,
            "capabilities": traits.capabilities,
            "contexts": traits.contexts,
        }.items()
        if values
    ]
    covered = {
        dim
        for candidate in selected
        for dim in candidate["matched_dimensions"]
    }
    coverage = (
        len(covered) / len(provided_dimensions)
        if provided_dimensions
        else 0.0
    )

    top_score = selected[0]["score"] if selected else 0
    if top_score >= SELECT_HIGH_SCORE and coverage >= SELECT_HIGH_COVERAGE:
        confidence = "high"
    elif (
        top_score >= SELECT_MEDIUM_SCORE
        and coverage >= SELECT_MEDIUM_COVERAGE
    ):
        confidence = "medium"
    else:
        confidence = "low"

    broadening_recommended = (
        not broaden
        and (
            len(provided_dimensions) <= 1
            or
            confidence == "low"
            or coverage < BROADEN_COVERAGE_FLOOR
            or any(candidate["uncertain"] for candidate in selected)
        )
    )

    return {
        "candidates": [
            {
                "name": candidate["name"],
                "latest_version": candidate["latest_version"],
                "kit_type": candidate["kit_type"],
                "score": candidate["score"],
                "confidence": candidate["confidence"],
                "reasons": candidate["reasons"],
                "summary": candidate["summary"],
            }
            for candidate in selected
        ],
        "confidence": confidence,
        "coverage": round(coverage, 3),
        "broadening_recommended": broadening_recommended,
        "warnings": warnings,
    }


def explain_kit_v2(
    *,
    name: str,
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    capabilities: list[str] | None = None,
    contexts: list[str] | None = None,
) -> dict[str, Any]:
    """
    Explain why a specific kit is or is not a good fit.

    :param name: Kit name to evaluate.
    :param languages: Project language hints.
    :param frameworks: Framework hints.
    :param capabilities: Capability hints.
    :param contexts: Context hints.
    :returns: Candidate diagnostics with structured constraints.
    :raises KitNotFoundError: If no kit with *name* exists.
    """
    traits = _normalize_traits(
        languages=languages,
        frameworks=frameworks,
        capabilities=capabilities,
        contexts=contexts,
    )
    catalog, _warnings = _catalog_entries()
    entries = {
        info.name: (info, applicability)
        for info, applicability in catalog
    }
    if name not in entries:
        raise KitNotFoundError(name)
    info, applicability = entries[name]
    evaluation = _evaluate_candidate(info, applicability, traits)
    return {
        "name": info.name,
        "latest_version": info.latest_version,
        "summary": applicability.summary,
        "kit_type": applicability.kit_type,
        "requires": applicability.requires,
        "excludes": applicability.excludes,
        "related_kits": applicability.related_kits,
        "score": evaluation["score"],
        "confidence": evaluation["confidence"],
        "ineligible": evaluation["ineligible"],
        "uncertain": evaluation["uncertain"],
        "reasons": evaluation["reasons"],
    }


def _resolve_kit_version(
    name: str,
    version: str | None = None,
    root: Path | None = None,
    subject: Any = _CTX_SUBJECT,
) -> tuple[str, Path]:
    """
    Resolve a kit name and optional version to its index path.

    :param name: Kit name as returned by :func:`list_all_kits`.
    :param version: Major version string, e.g. ``"v1"``.  Defaults to
        the latest available version when omitted.
    :param root: When given, resolve within this specific root only
        (used by layer-specific read/write operations).  When ``None``,
        use the merged catalog across all configured layers.
    :returns: Tuple of ``(resolved_version, index_toml_path)``.
    :raises KitNotFoundError: If no kit with *name* exists.
    :raises KitVersionNotFoundError: If *version* does not exist for
        the kit.
    """
    if root is not None:
        all_versions = _kit_version_paths(root)
        if name not in all_versions:
            logger.debug("resolve(root=%s): kit %r not found", root, name)
            raise KitNotFoundError(name)
        versions = all_versions[name]
    else:
        layers = _caller_layers(subject)
        layered = _kit_version_paths_layered(layers)
        if name not in layered:
            logger.debug("resolve: kit %r not found", name)
            raise KitNotFoundError(name)
        # Extract simple {version: index_path} for the kit
        versions = {v: data[0] for v, data in layered[name].items()}
    resolved = version or max(versions, key=_version_key)
    if resolved not in versions:
        logger.debug("resolve: version %r not found for kit %r", resolved, name)
        raise KitVersionNotFoundError(name, resolved)
    return resolved, versions[resolved]


def read_kit_outline(
    name: str,
    version: str | None = None,
    root: Path | None = None,
    subject: Any = _CTX_SUBJECT,
) -> dict[str, Any]:
    """
    Return a cheap section map for a kit without loading section bodies.

    Read this before :func:`read_kit` to decide which sections the
    current task needs, then pull only those.

    In the default merged mode (``root=None``), binding sections from
    lower-priority base layers are included even when the kit is
    shadowed by a higher-priority overlay layer.

    :param name: Kit name as returned by :func:`list_all_kits`.
    :param version: Major version string; defaults to the latest.
    :param root: When given, return the outline for exactly this root
        (no binding-section merging). Used by layer-specific reads.
    :returns: ``{name, version, summary, sections}`` where each section
        is ``{id, title, gloss, always_load, binding, bytes}``.
    :raises KitNotFoundError: If no kit with *name* exists.
    :raises KitVersionNotFoundError: If *version* does not exist.
    """
    if root is not None:
        resolved, index_path = _resolve_kit_version(name, version, root=root)
        index = _load_kit_index(index_path, name)
        instr_dir = index_path.parent
        sections = [
            {
                "id": s.id,
                "title": s.title,
                "gloss": s.gloss,
                "always_load": s.always_load,
                "binding": s.binding,
                "bytes": (instr_dir / s.file).stat().st_size,
            }
            for s in index.sections
        ]
        return {
            "name": name,
            "version": resolved,
            "summary": index.summary,
            "sections": sections,
        }

    # Merged mode: include binding contributions from lower-priority layers
    resolved, primary_index_path, binding_contribs = _resolve_merged_kit(
        name, version, subject=subject
    )
    primary_index = _load_kit_index(primary_index_path, name)
    primary_instr_dir = primary_index_path.parent

    binding_ids = {s.id for s, _ in binding_contribs}
    merged: list[tuple[KitSection, Path]] = list(binding_contribs)
    for s in primary_index.sections:
        if s.id not in binding_ids:
            merged.append((s, primary_instr_dir))

    sections = [
        {
            "id": s.id,
            "title": s.title,
            "gloss": s.gloss,
            "always_load": s.always_load,
            "binding": s.binding,
            "bytes": (d / s.file).stat().st_size,
        }
        for s, d in merged
    ]
    return {
        "name": name,
        "version": resolved,
        "summary": primary_index.summary,
        "sections": sections,
    }


def read_kit(
    name: str,
    version: str | None = None,
    sections: list[str] | None = None,
    root: Path | None = None,
    subject: Any = _CTX_SUBJECT,
) -> str:
    """
    Return the content of a named instruction kit.

    In the default merged mode (``root=None``), binding sections from
    lower-priority base layers are included even when the kit is
    shadowed by a higher-priority overlay layer.

    :param name: Kit name as returned by :func:`list_all_kits`.
    :param version: Major version string, e.g. ``"v1"``.  Defaults to
        the latest available version when omitted.
    :param sections: Optional list of section ids (see
        :func:`read_kit_outline`).  When omitted, all sections are
        concatenated in document order — the complete instructions.
        When given, only those sections are returned, in document order.
    :param root: When given, read from exactly this root (no binding-
        section merging). Used by layer-specific reads.
    :returns: UTF-8 Markdown for the requested sections.
    :raises KitNotFoundError: If no kit with *name* exists.
    :raises KitVersionNotFoundError: If *version* does not exist.
    :raises KitSectionNotFoundError: If a requested section id is
        unknown for the kit.
    """
    logger.debug(
        "read_kit: name=%r version=%r sections=%r root=%r",
        name, version, sections, root,
    )

    if root is not None:
        # Layer-specific read: no binding-section merging
        resolved, index_path = _resolve_kit_version(name, version, root=root)
        index = _load_kit_index(index_path, name)
        instr_dir = index_path.parent
        selected_sections = index.sections
        if sections is not None:
            by_id = {s.id: s for s in index.sections}
            unknown = [s for s in sections if s not in by_id]
            if unknown:
                raise KitSectionNotFoundError(
                    name, unknown, [s.id for s in index.sections]
                )
            wanted = set(sections)
            selected_sections = [s for s in index.sections if s.id in wanted]
        bodies = [
            (instr_dir / s.file).read_text(encoding="utf-8").strip("\n")
            for s in selected_sections
        ]
        return "\n\n".join(bodies) + "\n"

    # Merged read: include binding contributions from lower-priority layers
    resolved, primary_index_path, binding_contribs = _resolve_merged_kit(
        name, version, subject=subject
    )
    primary_index = _load_kit_index(primary_index_path, name)
    primary_instr_dir = primary_index_path.parent

    binding_ids = {s.id for s, _ in binding_contribs}
    merged: list[tuple[KitSection, Path]] = list(binding_contribs)
    for s in primary_index.sections:
        if s.id not in binding_ids:
            merged.append((s, primary_instr_dir))

    if sections is not None:
        all_ids = {s.id for s, _ in merged}
        unknown = [s for s in sections if s not in all_ids]
        if unknown:
            raise KitSectionNotFoundError(
                name, unknown, [s.id for s, _ in merged]
            )
        wanted = set(sections)
        merged = [(s, d) for s, d in merged if s.id in wanted]

    bodies = [
        (d / s.file).read_text(encoding="utf-8").strip("\n")
        for s, d in merged
    ]
    return "\n\n".join(bodies) + "\n"


def compare_kit_versions(
    name: str,
    from_version: str,
    to_version: str,
) -> dict:
    """
    Summarise changes between two kit versions using ``CHANGELOG.md``.

    Reads ``kits/<name>/CHANGELOG.md`` and returns every section whose
    version label falls strictly after *from_version* and up to and
    including *to_version* (versions are compared semantically).
    The argument order does not matter — the function normalises the
    range so that the lower version is always the exclusive lower bound.

    A ``user_facing_warning`` flag is set when any returned section
    contains keywords associated with end-user impact (authentication,
    API routes, passwords, sessions, breaking changes, schema, etc.).

    :param name: Kit name.
    :param from_version: One end of the version range (exclusive), e.g.
        ``"v1.0.0"``.
    :param to_version: Other end of the version range (inclusive), e.g.
        ``"v2.0.0"``.
    :returns: Dict with keys:

        ``changes``
            List of ``{"version": str, "summary": str}`` dicts for
            each changelog section in the requested range, ordered
            from oldest to newest.

        ``user_facing_warning``
            ``True`` when any change section contains keywords
            suggesting an impact on end-users.

    :raises KitNotFoundError: If no kit with *name* exists.
    :raises FileNotFoundError: If the kit has no ``CHANGELOG.md``.
    """
    logger.debug(
        "compare_kit_versions: name=%r %r..%r", name, from_version, to_version
    )
    layers = _caller_layers()
    kit_dir: Path | None = None
    for layer in reversed(layers):
        candidate = layer.path / name
        if candidate.is_dir():
            kit_dir = candidate
            break
    if kit_dir is None:
        raise KitNotFoundError(name)
    changelog_path = kit_dir / "CHANGELOG.md"
    if not changelog_path.exists():
        raise FileNotFoundError(
            f"No CHANGELOG.md found for kit {name!r}"
        )

    sections = _parse_changelog(
        changelog_path.read_text(encoding="utf-8")
    )

    from_tuple = _parse_version_tuple(from_version)
    to_tuple = _parse_version_tuple(to_version)

    # Normalise ordering so the range is always lo < v <= hi,
    # regardless of whether the caller passes (from, to) or (to, from).
    lo, hi = (
        (from_tuple, to_tuple)
        if from_tuple <= to_tuple
        else (to_tuple, from_tuple)
    )

    selected = {
        v: body
        for v, body in sections.items()
        if lo < _parse_version_tuple(v) <= hi
    }

    # Sort selected sections oldest → newest.
    ordered = dict(
        sorted(
            selected.items(),
            key=lambda kv: _parse_version_tuple(kv[0]),
        )
    )

    user_facing = any(
        bool(_USER_FACING_RE.search(body))
        for body in ordered.values()
    )

    return {
        "changes": [
            {"version": v, "summary": body}
            for v, body in ordered.items()
        ],
        "user_facing_warning": user_facing,
    }


# ---------------------------------------------------------------------------
# Version pinning: effective-version resolution and upgrade advisories
# ---------------------------------------------------------------------------
#
# A target repo records which *major* version of a kit it follows in a
# repo-side ``.quartermaster.toml`` file (see the project docs). The server
# never stores or writes that pin; the calling agent reads the file and passes
# the pin in. The three agent-facing tools (``get_kit``, ``get_kit_outline``,
# ``resolve_kits``) resolve an *effective* version conservatively: an explicit
# version or a valid pin wins; otherwise, when a kit has more than one major,
# the earliest major is served and an upgrade *advisory* is attached so the
# agent can prompt the user to confirm or upgrade (and then write the pin).
# Single-version kits are unaffected — no pin, no advisory.


def _available_versions(name: str, subject: Any = _CTX_SUBJECT) -> list[str]:
    """
    Return the available major versions for a kit, oldest → newest.

    :param name: Kit name as returned by :func:`list_all_kits`.
    :param subject: Caller identity for private-kit visibility.
    :returns: Sorted list of ``v<N>`` labels.
    :raises KitNotFoundError: If no kit with *name* exists.
    """
    layers = _caller_layers(subject)
    layered = _kit_version_paths_layered(layers)
    if name not in layered:
        raise KitNotFoundError(name)
    return sorted(layered[name].keys(), key=_version_key)


def _read_changelog_sections(
    name: str, subject: Any = _CTX_SUBJECT
) -> dict[str, str]:
    """
    Return the parsed ``CHANGELOG.md`` sections for a kit, or ``{}``.

    Unlike :func:`compare_kit_versions`, this never raises when the kit
    has no changelog — an advisory must degrade gracefully rather than
    fail a resolve.

    :param name: Kit name.
    :param subject: Caller identity for layer resolution.
    :returns: Mapping of version label → section body (empty if absent).
    """
    for layer in reversed(_caller_layers(subject)):
        changelog_path = layer.path / name / "CHANGELOG.md"
        if changelog_path.exists():
            return _parse_changelog(
                changelog_path.read_text(encoding="utf-8")
            )
    return {}


def _empty_version_policy() -> dict[str, Any]:
    """Return the default (no-constraint) advisory ``policy`` block."""
    return {"min_version": None, "deprecated": []}


def _version_policy_for(name: str) -> dict[str, Any]:
    """
    Return the operator version policy for *name*, or the empty policy.

    Settings access is tolerant of an unconfigured/invalid environment
    (mirrors the resolver's engine-config handling) — any failure yields
    no policy rather than breaking a resolve.
    """
    try:
        pol = get_settings().version_policy().get(name)
    except Exception:  # noqa: BLE001 - policy is advisory, never fatal
        return _empty_version_policy()
    if not pol:
        return _empty_version_policy()
    return {
        "min_version": pol.get("min_version"),
        "deprecated": list(pol.get("deprecated", [])),
    }


def _conservative_default_enabled() -> bool:
    """Whether unpinned multi-version kits serve their earliest major."""
    try:
        return bool(get_settings().conservative_default_enabled)
    except Exception:  # noqa: BLE001
        return True


def _build_version_advisory(
    name: str,
    served: str,
    latest: str,
    versions: list[str],
    *,
    reason: str,
    policy: dict[str, Any] | None = None,
    subject: Any = _CTX_SUBJECT,
) -> dict[str, Any]:
    """
    Build the ``version_advisory`` block for a served-below-latest kit.

    Reuses the changelog machinery (:func:`_parse_changelog`,
    :data:`_USER_FACING_RE`) to summarise the breaking changes a caller
    would take on by upgrading from *served* to *latest*. Only changelog
    entries whose **major** version is greater than *served*'s and up to
    and including *latest*'s are included, so a v1→v2 advisory surfaces
    the v2 breaking changes without repeating minor v1.x history.

    :param name: Kit name.
    :param served: The version actually being served (conservative pick).
    :param latest: The highest available version.
    :param versions: All available versions, oldest → newest.
    :param reason: Why the advisory fired (``unpinned-multi-version``,
        ``pin-invalid``, or ``policy-min-version``).
    :param policy: Optional operator policy block; defaults to empty.
    :param subject: Caller identity for changelog resolution.
    :returns: The ``version_advisory`` dict.
    """
    served_major = _version_key(served)
    latest_major = _version_key(latest)
    breaking_changes: list[dict[str, str]] = []
    user_facing = False
    if served_major < latest_major:
        sections = _read_changelog_sections(name, subject)
        selected = {
            v: body
            for v, body in sections.items()
            if served_major < _parse_version_tuple(v)[0] <= latest_major
        }
        ordered = sorted(
            selected.items(), key=lambda kv: _parse_version_tuple(kv[0])
        )
        breaking_changes = [
            {"version": v, "summary": body} for v, body in ordered
        ]
        user_facing = any(
            bool(_USER_FACING_RE.search(body)) for _v, body in ordered
        )
    return {
        "kit": name,
        "served_version": served,
        "latest_version": latest,
        "available_versions": versions,
        "reason": reason,
        "breaking_changes": breaking_changes,
        "user_facing_warning": user_facing,
        "policy": policy or _empty_version_policy(),
        "action_required": "confirm_and_pin",
        "pin_file_hint": {
            "path": ".quartermaster.toml",
            "table": "kits",
            "key": name,
        },
    }


def resolve_effective_version(
    name: str,
    *,
    version: str | None = None,
    pin: str | None = None,
    subject: Any = _CTX_SUBJECT,
) -> tuple[str, dict[str, Any] | None]:
    """
    Resolve the version a caller should be served, plus any advisory.

    Decision order:

    * an explicit *version* (validated) always wins, no advisory;
    * a valid *pin* wins, no advisory;
    * an *invalid* pin (a rolled-back or removed version) falls back to
      the conservative default with a ``pin-invalid`` advisory — it
      never raises, so a stale pin cannot brick a resolve;
    * with no version or pin and a single available version, that
      version is served with no advisory;
    * with no version or pin and multiple versions, the **earliest**
      major is served (an unpinned repo predates the split) with an
      ``unpinned-multi-version`` advisory.

    This deliberately does not touch :func:`_resolve_kit_version`'s
    latest-wins default; only the agent-facing tools call this helper and
    pass the resolved version down explicitly.

    :param name: Kit name.
    :param version: Explicit version override, if any.
    :param pin: The repo-side pin the agent read, if any.
    :param subject: Caller identity for version/changelog resolution.
    :returns: ``(served_version, advisory_or_None)``.
    :raises KitNotFoundError: If no kit with *name* exists.
    :raises KitVersionNotFoundError: If an explicit *version* is unknown.
    """
    versions = _available_versions(name, subject)
    latest = max(versions, key=_version_key)
    earliest = min(versions, key=_version_key)

    # An explicit version or a valid pin is authoritative — no advisory.
    if version is not None:
        if version not in versions:
            raise KitVersionNotFoundError(name, version)
        return version, None
    if pin is not None and pin in versions:
        return pin, None

    pin_invalid = pin is not None  # present but not among available versions
    if len(versions) == 1 and not pin_invalid:
        return versions[0], None

    # Conservative default: serve the earliest major (an unpinned repo predates
    # the split) unless the operator reverted to latest-wins.
    served = earliest if _conservative_default_enabled() else latest
    reason = "pin-invalid" if pin_invalid else "unpinned-multi-version"

    # Operator policy floor: never serve below a declared minimum major.
    policy = _version_policy_for(name)
    min_version = policy.get("min_version")
    if (
        min_version in versions
        and _version_key(served) < _version_key(min_version)
    ):
        served = min_version
        reason = "policy-min-version"

    # Nothing to advise when latest is served for a non-pin, non-policy reason.
    if (
        served == latest
        and not pin_invalid
        and reason != "policy-min-version"
    ):
        return served, None

    advisory = _build_version_advisory(
        name, served, latest, versions,
        reason=reason, policy=policy, subject=subject,
    )
    return served, advisory
