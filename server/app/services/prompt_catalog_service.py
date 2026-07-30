"""
Prompt CRUD business logic (validate-before-commit).

Every mutation renders the proposed file content, parses it back with the
*same* frontmatter parser the read path uses
(:func:`app.prompt_catalog._parse_frontmatter`), and only commits the write
(:func:`~app.storage.catalog_writes.atomic_write_text`) once that round-trip
succeeds. A write that would produce unparseable content is rejected with
:class:`~app.prompt_catalog.PromptValidationError` and the on-disk state is
untouched. Unlike kits, prompt content is a single file, so there is no
staging-directory/atomic-swap step — a single atomic file write is the whole
commit.

The layer reuses ``app.prompt_catalog`` for all reads and path resolution,
mirroring ``app.services.kit_service``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app import prompt_catalog as prompts_mod
from app.catalog.errors import (
    CatalogLayerNotFoundError,
    CatalogLayerReadonlyError,
)
from app.prompt_catalog import (
    PromptConflictError,
    PromptDetail,
    PromptLayerNotFoundError,
    PromptLayerReadonlyError,
    PromptNotFoundError,
    PromptValidationError,
)
from app.services import catalog_service as catalog_svc
from app.storage import prompt_writes as writes

__all__ = [
    "list_prompts",
    "list_layers",
    "get_prompt_detail",
    "put_prompt",
    "delete_prompt",
]


def _prompts_write_root() -> Path:
    """Return the default writable layer root (last non-readonly layer)."""
    settings = prompts_mod.get_settings()
    layers = prompts_mod._get_effective_layers(settings)
    try:
        return catalog_svc.default_write_root(layers)
    except RuntimeError as exc:
        raise RuntimeError(
            "No writable prompt layer configured. "
            "Set QM_PROMPTS_ROOT or configure at least one non-readonly "
            "layer in QM_PROMPT_LAYERS_FILE."
        ) from exc


def _layer_path(layer_id: str) -> Path:
    """
    Return the path for a named prompt layer (read access, no readonly check).

    :raises PromptLayerNotFoundError: If no such layer is configured.
    """
    settings = prompts_mod.get_settings()
    layers = prompts_mod._get_effective_layers(settings)
    try:
        return catalog_svc.layer_path(layers, layer_id)
    except CatalogLayerNotFoundError as exc:
        raise PromptLayerNotFoundError(layer_id) from exc


def _layer_write_path(layer_id: str) -> Path:
    """
    Return the path for a named prompt layer and enforce it is writable.

    :raises PromptLayerNotFoundError: If no such layer is configured.
    :raises PromptLayerReadonlyError: If the layer is read-only for REST.
    """
    settings = prompts_mod.get_settings()
    layers = prompts_mod._get_effective_layers(settings)
    try:
        return catalog_svc.layer_write_path(layers, layer_id)
    except CatalogLayerReadonlyError as exc:
        raise PromptLayerReadonlyError(layer_id) from exc
    except CatalogLayerNotFoundError as exc:
        raise PromptLayerNotFoundError(layer_id) from exc


def _layer_rest_editable(source_layer: str | None) -> bool:
    """Return whether a prompt owned by *source_layer* is editable over REST."""
    settings = prompts_mod.get_settings()
    layers = prompts_mod._get_effective_layers(settings)
    return catalog_svc.layer_rest_editable(layers, source_layer)


def _static_prompt_names() -> set[str]:
    """Return the names reserved by statically-registered canned prompts.

    FastMCP resolves a static (decorator-registered) prompt before any
    provider-sourced one of the same name, so a catalog prompt sharing a
    canned prompt's name would be silently unreachable over MCP. Writes
    must reject that collision outright rather than create a dead entry.
    """
    from app.prompts import _PROMPTS

    return {p["name"] for p in _PROMPTS}


def list_prompts() -> list[dict[str, Any]]:
    """
    List all catalog prompts with compact metadata.

    :returns: List of ``{name, title, description, source_layer, editable,
        broken, error}``.
    """
    return [
        {
            "name": p.name,
            "title": p.title,
            "description": p.description,
            "source_layer": p.source_layer,
            "editable": _layer_rest_editable(p.source_layer),
            "broken": p.broken,
            "error": p.error,
        }
        for p in prompts_mod.list_all_prompts()
    ]


def list_layers() -> list[dict[str, Any]]:
    """
    Return metadata for all configured prompt layers.

    :returns: List of ``{name, path, readonly, rest_readonly,
        webdav_readonly}`` dicts, ordered base → overlay. Empty when no
        prompt layer is configured (a valid steady state for prompts).
    """
    settings = prompts_mod.get_settings()
    layers = prompts_mod._get_effective_layers(settings)
    return catalog_svc.list_layers(layers)


def _require_prompt(name: str, root: Path | None = None) -> None:
    """
    Raise :class:`PromptNotFoundError` if *name* is not a known prompt.

    When *root* is given, checks only that root; when ``None``, checks the
    merged catalog across all configured layers.
    """
    if root is not None:
        exists = name in prompts_mod._prompt_paths(root)
    else:
        exists = any(p.name == name for p in prompts_mod.list_all_prompts())
    catalog_svc.require_exists(name, exists, not_found=PromptNotFoundError)


def get_prompt_detail(name: str, root: Path | None = None) -> dict[str, Any]:
    """
    Return a single prompt's metadata and body.

    :param name: Prompt name.
    :param root: When given, read from this root only (layer-specific).
    :returns: ``{name, title, description, source_layer, editable, body}``
        for the merged view (layer-specific view omits ``source_layer``/
        ``editable``).
    :raises PromptNotFoundError: If the prompt does not exist.
    """
    detail = prompts_mod.read_prompt(name, root=root)
    result: dict[str, Any] = {
        "name": detail.name,
        "title": detail.title,
        "description": detail.description,
        "body": detail.body,
    }
    if root is None:
        result["source_layer"] = detail.source_layer
        result["editable"] = _layer_rest_editable(detail.source_layer)
    return result


def _round_trip_or_raise(title: str, description: str, body: str) -> None:
    """
    Render the proposed prompt file and parse it back before any write.

    :raises PromptValidationError: If the rendered content does not parse,
        or does not round-trip back to the same title/description/body.
    """
    rendered = prompts_mod.render_prompt_file(title, description, body)
    meta, parsed_body = prompts_mod._parse_frontmatter(rendered)
    if (
        meta.get("title", "") != title
        or meta.get("description", "") != description
        or parsed_body != body
    ):
        raise PromptValidationError(
            "Prompt content does not round-trip through the frontmatter "
            "parser (check for newlines or stray ':' in title/description)."
        )


def put_prompt(
    name: str,
    title: str,
    description: str,
    body: str,
    root: Path | None = None,
) -> PromptDetail:
    """
    Create or replace a prompt (idempotent PUT).

    :param name: Prompt name.
    :param title: Prompt title (frontmatter), or ``""`` to omit.
    :param description: Prompt description (frontmatter), or ``""`` to omit.
    :param body: Markdown body.
    :param root: Target root; defaults to the default writable layer.
    :returns: The stored prompt detail.
    :raises PromptConflictError: If *name* collides with a statically
        registered canned prompt (see :func:`_static_prompt_names`).
    :raises PromptValidationError: If the content does not round-trip.
    """
    writes.validate_prompt_name(name)
    if name in _static_prompt_names():
        raise PromptConflictError(
            f"Prompt name {name!r} is reserved by a built-in canned "
            f"prompt and cannot be used in the prompts catalog."
        )
    _round_trip_or_raise(title, description, body)

    effective_root = root or _prompts_write_root()
    path = writes.resolve_within(effective_root, f"{name}.md")
    writes.atomic_write_text(
        path, prompts_mod.render_prompt_file(title, description, body)
    )
    return prompts_mod.read_prompt(name, root=effective_root)


def delete_prompt(name: str, root: Path | None = None) -> None:
    """
    Delete a prompt. Idempotent.

    :param name: Prompt name (no error if it does not exist).
    :param root: Target root; defaults to the default writable layer.
    """
    writes.validate_prompt_name(name)
    effective_root = root or _prompts_write_root()
    path = writes.resolve_within(effective_root, f"{name}.md")
    writes.remove_path(path)
