"""
Prompt discovery and content access.

A prompt is a single Markdown file, ``<layer-root>/<name>.md``, holding an
optional frontmatter block (``title``/``description``) followed by a body —
the reusable agent instruction text. Unlike kits, prompts have no versions
and no sections: the whole file is the content.

This is deliberately distinct from the existing, unrelated :mod:`app.prompts`
module (canned onboarding templates shipped with the server) — do not
conflate the two.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.catalog import layering as _layering
from app.catalog.errors import (
    CatalogConflictError,
    CatalogLayerNotFoundError,
    CatalogLayerReadonlyError,
    CatalogNotFoundError,
    CatalogValidationError,
)
from app.catalog.merge import scan_layers_merged
from app.config import KitLayerConfig, get_settings
from app.private_prompts import owned_private_roots

logger = logging.getLogger(__name__)


class PromptNotFoundError(CatalogNotFoundError):
    """
    Raised when a requested prompt name does not match any known prompt.

    :param name: The prompt name that was requested.
    """

    def __init__(self, name: str) -> None:
        super().__init__(f"Prompt not found: {name!r}")
        self.name = name


class PromptConflictError(CatalogConflictError):
    """
    Raised when a write would collide with existing content, or with a
    statically-registered canned prompt name.

    :param message: Human-readable description of the collision.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PromptValidationError(CatalogValidationError):
    """
    Raised when proposed prompt content is invalid.

    Covers malformed frontmatter (an unrecognized key, or a block that
    never closes) — the write is rejected before any bytes are committed.

    :param message: Human-readable validation failure description.
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PromptLayerNotFoundError(CatalogLayerNotFoundError):
    """
    Raised when a requested prompt layer identifier is not configured.

    :param layer_name: The layer name that was requested.
    """

    def __init__(self, layer_name: str) -> None:
        super().__init__(f"Prompt layer not found: {layer_name!r}")
        self.layer_name = layer_name


class PromptLayerReadonlyError(CatalogLayerReadonlyError):
    """
    Raised when a write is attempted on a read-only prompt layer.

    :param layer_name: The layer name that is read-only.
    """

    def __init__(self, layer_name: str) -> None:
        super().__init__(f"Prompt layer {layer_name!r} is read-only")
        self.layer_name = layer_name


@dataclass(frozen=True)
class PromptInfo:
    """
    Lightweight metadata for a single catalog prompt.

    :param name: The prompt's stable name (the ``.md`` file's stem).
    :param title: Frontmatter ``title``, or ``""`` if absent.
    :param description: Frontmatter ``description``, or ``""`` if absent.
    :param source_layer: Name of the layer that owns this prompt (the
        highest-priority layer containing it). ``None`` in legacy
        single-root usage.
    :param broken: True when the prompt file could not be parsed (missing
        frontmatter close, or an unrecognized frontmatter key). A broken
        prompt is still listed (so it can be surfaced and fixed) but is
        excluded from serving.
    :param error: Human-readable reason the prompt is broken, or ``None``.
    """

    name: str
    title: str
    description: str
    source_layer: str | None = None
    broken: bool = False
    error: str | None = None


@dataclass(frozen=True)
class PromptDetail(PromptInfo):
    """A single prompt's full metadata plus its Markdown body."""

    body: str = ""


# Prompt file basenames: lowercase words joined by single hyphens, matching
# the kit-name convention (e.g. "release-checklist").
_PROMPT_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")

# The only frontmatter keys this hand-rolled parser recognizes. Anything
# else is a hard validation error — fail fast rather than silently drop
# unknown metadata (mirrors app.kits' index parsing).
_ALLOWED_FRONTMATTER_KEYS = {"title", "description"}


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """
    Parse an optional leading frontmatter block, returning ``(meta, body)``.

    A file with no leading ``---`` line has no frontmatter: ``({}, text)``
    is returned unchanged (body-only content is valid). A leading ``---``
    starts a frontmatter block that must close with another ``---`` line;
    each line inside is a flat ``key: value`` pair restricted to
    :data:`_ALLOWED_FRONTMATTER_KEYS`.

    :param text: Raw file content.
    :returns: ``(meta, body)`` where *meta* has only recognized keys.
    :raises PromptValidationError: If the frontmatter block never closes,
        contains a line with no ``:``, or an unrecognized key.
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_idx: int | None = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        raise PromptValidationError(
            "Frontmatter block is not closed with a '---' line"
        )

    meta: dict[str, str] = {}
    for line in lines[1:end_idx]:
        if not line.strip():
            continue
        if ":" not in line:
            raise PromptValidationError(
                f"Malformed frontmatter line (expected 'key: value'): "
                f"{line!r}"
            )
        key, _, value = line.partition(":")
        key = key.strip()
        if key not in _ALLOWED_FRONTMATTER_KEYS:
            raise PromptValidationError(
                f"Unknown frontmatter key {key!r}; expected one of "
                f"{sorted(_ALLOWED_FRONTMATTER_KEYS)}"
            )
        meta[key] = value.strip()

    body = "\n".join(lines[end_idx + 1 :])
    return meta, body


def render_prompt_file(title: str, description: str, body: str) -> str:
    """
    Render a prompt's frontmatter + body into the on-disk file format.

    Omits the frontmatter block entirely when both *title* and
    *description* are empty, so a body-only prompt stays body-only on
    disk. Inverse of :func:`_parse_frontmatter`.

    :param title: Prompt title, or ``""`` to omit.
    :param description: Prompt description, or ``""`` to omit.
    :param body: Markdown body.
    :returns: The full file text to write.
    """
    if not title and not description:
        return body
    lines = ["---"]
    if title:
        lines.append(f"title: {title}")
    if description:
        lines.append(f"description: {description}")
    lines.append("---")
    lines.append(body)
    return "\n".join(lines)


def _prompt_paths(root: Path) -> dict[str, Path]:
    """
    Scan *root* for prompt Markdown files.

    :param root: A prompt layer's root directory.
    :returns: Mapping of prompt name (file stem) → ``.md`` path, for
        every directly-contained file whose stem is a valid prompt name.
    """
    result: dict[str, Path] = {}
    if not root.is_dir():
        return result
    for p in sorted(root.glob("*.md")):
        name = p.stem
        if not _PROMPT_NAME_RE.fullmatch(name):
            continue
        result[name] = p
    return result


def _get_effective_layers(settings: Any) -> list[KitLayerConfig]:
    """Return the configured prompt layers from *settings* (possibly empty)."""
    return list(settings.effective_prompt_layers)


# Prompt-specific aliases over the generic layering primitives, kept under
# these names for a consistent style with app.kits.
CTX_SUBJECT: Any = _layering.CTX_SUBJECT
_PRIVATE_LAYER_NAME = _layering.PRIVATE_LAYER_NAME


def _caller_layers(subject: Any = CTX_SUBJECT) -> list[KitLayerConfig]:
    """Return the effective prompt layers for a caller, private overlay last.

    Thin prompt-specific binding over
    :func:`app.catalog.layering.caller_layers`: supplies this catalog's
    configured public layers and :func:`app.private_prompts.owned_private_roots`
    as the private-root lookup.

    :param subject: ``CTX_SUBJECT`` (contextvar), a ``str`` subject, or
        ``None`` to force public-only.
    :returns: Ordered layers, base → overlay, private overlay last if any.
    """
    settings = get_settings()
    base_layers = _get_effective_layers(settings)
    return _layering.caller_layers(
        base_layers, owned_private_roots, subject=subject
    )


def _prompt_paths_layered(
    layers: list[KitLayerConfig],
) -> dict[str, tuple[Path, Path, str]]:
    """Scan multiple prompt layers and merge with whole-name shadowing."""
    return scan_layers_merged(layers, _prompt_paths)


def _load_prompt_meta(path: Path) -> tuple[str, str]:
    """
    Parse a prompt file's frontmatter and return ``(title, description)``.

    :raises PromptValidationError: If the frontmatter is malformed.
    """
    text = path.read_text(encoding="utf-8")
    meta, _body = _parse_frontmatter(text)
    return meta.get("title", ""), meta.get("description", "")


def list_all_prompts(subject: Any = CTX_SUBJECT) -> list[PromptInfo]:
    """
    Return metadata for all available catalog prompts (merged view).

    In a multi-layer setup, prompt names present in multiple layers are
    represented once, from the highest-priority (overlay) layer. The
    caller's own private prompts (if any) are merged in as the
    highest-priority overlay; no other caller's private prompts are ever
    visible.

    :param subject: Caller identity for private-prompt visibility (see
        :func:`_caller_layers`).
    :returns: List of :class:`PromptInfo`, sorted alphabetically by name.
    """
    layers = _caller_layers(subject)
    prompts: list[PromptInfo] = []
    for name, (path, _layer_root, layer_name) in _prompt_paths_layered(
        layers
    ).items():
        try:
            title, description = _load_prompt_meta(path)
            prompts.append(
                PromptInfo(
                    name=name,
                    title=title,
                    description=description,
                    source_layer=layer_name,
                )
            )
        except (PromptValidationError, OSError) as exc:
            logger.warning("prompt %r is malformed: %s", name, exc)
            prompts.append(
                PromptInfo(
                    name=name,
                    title="",
                    description="",
                    source_layer=layer_name,
                    broken=True,
                    error=str(exc),
                )
            )
    return prompts


def list_private_prompts(subject: str) -> list[PromptInfo]:
    """
    Return only the private prompts owned by *subject* (never public ones).

    :param subject: The owner's stable subject.
    :returns: The owner's private :class:`PromptInfo` entries, sorted by
        name. Empty for an owner with no private catalog.
    """
    if not subject:
        return []
    return [
        prompt
        for prompt in list_all_prompts(subject=subject)
        if prompt.source_layer == _PRIVATE_LAYER_NAME
    ]


def _resolve_prompt_root(
    name: str, subject: Any = CTX_SUBJECT
) -> tuple[Path, str]:
    """
    Return the root and layer name for the highest-priority layer
    containing *name*.

    :raises PromptNotFoundError: If no configured layer contains *name*.
    """
    layers = _caller_layers(subject)
    for layer in reversed(layers):
        if name in _prompt_paths(layer.path):
            return layer.path, layer.name
    raise PromptNotFoundError(name)


def read_prompt(
    name: str,
    subject: Any = CTX_SUBJECT,
    root: Path | None = None,
) -> PromptDetail:
    """
    Return a single prompt's parsed metadata and body.

    :param name: Prompt name (file stem).
    :param subject: Caller identity for private-prompt visibility; ignored
        when *root* is given.
    :param root: When given, read from exactly this layer root (used by
        layer-scoped and private-overlay reads). When ``None``, resolve
        via the merged catalog across all configured layers.
    :returns: The prompt's full detail, including its body.
    :raises PromptNotFoundError: If no prompt with *name* exists.
    :raises PromptValidationError: If the prompt's frontmatter is malformed.
    """
    if root is not None:
        paths = _prompt_paths(root)
        if name not in paths:
            raise PromptNotFoundError(name)
        path = paths[name]
        layer_name: str | None = None
    else:
        effective_root, layer_name = _resolve_prompt_root(name, subject)
        path = _prompt_paths(effective_root)[name]

    text = path.read_text(encoding="utf-8")
    meta, body = _parse_frontmatter(text)
    return PromptDetail(
        name=name,
        title=meta.get("title", ""),
        description=meta.get("description", ""),
        source_layer=layer_name,
        body=body,
    )
