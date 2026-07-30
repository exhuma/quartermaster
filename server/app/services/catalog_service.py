"""
Generic layer-selection and readonly-enforcement helpers for a layered
directory catalog's write path.

Extracted from ``app.services.kit_service``: these functions are already
generic over a ``list[KitLayerConfig]`` (plus, for existence checks, a
caller-supplied predicate), with no kit-specific behavior baked in.
``app.services.kit_service`` rewires them to kit settings/errors; a future
second catalog type's service module would do the same.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.catalog.errors import (
    CatalogLayerNotFoundError,
    CatalogLayerReadonlyError,
)
from app.config import KitLayerConfig


def default_write_root(layers: list[KitLayerConfig]) -> Path:
    """
    Return the default writable layer root: the last non-readonly layer.

    :param layers: Configured layers, base → overlay.
    :returns: The path of the last layer that is not REST-readonly.
    :raises RuntimeError: If every configured layer is REST-readonly.
    """
    for layer in reversed(layers):
        if not layer.rest_readonly:
            return layer.path
    raise RuntimeError(
        "No writable layer configured: every configured layer is "
        "REST-readonly."
    )


def layer_path(layers: list[KitLayerConfig], layer_id: str) -> Path:
    """
    Return the path for a named layer (read access, no readonly check).

    :param layers: Configured layers, base → overlay.
    :param layer_id: Layer name to look up.
    :returns: The layer's root path.
    :raises CatalogLayerNotFoundError: If no such layer is configured.
    """
    for layer in layers:
        if layer.name == layer_id:
            return layer.path
    raise CatalogLayerNotFoundError(layer_id)


def layer_write_path(layers: list[KitLayerConfig], layer_id: str) -> Path:
    """
    Return the path for a named layer and enforce it is writable.

    :param layers: Configured layers, base → overlay.
    :param layer_id: Layer name to look up.
    :returns: The layer's root path.
    :raises CatalogLayerNotFoundError: If no such layer is configured.
    :raises CatalogLayerReadonlyError: If the layer is read-only for REST.
    """
    for layer in layers:
        if layer.name == layer_id:
            if layer.rest_readonly:
                raise CatalogLayerReadonlyError(layer_id)
            return layer.path
    raise CatalogLayerNotFoundError(layer_id)


def list_layers(layers: list[KitLayerConfig]) -> list[dict[str, Any]]:
    """
    Return metadata for every configured layer.

    :param layers: Configured layers, base → overlay.
    :returns: List of ``{name, path, readonly, rest_readonly,
        webdav_readonly}`` dicts, ordered base → overlay.
    """
    return [
        {
            "name": layer.name,
            "path": str(layer.path),
            "readonly": layer.readonly,
            "rest_readonly": layer.rest_readonly,
            "webdav_readonly": layer.webdav_readonly,
        }
        for layer in layers
    ]


def layer_rest_editable(
    layers: list[KitLayerConfig], source_layer: str | None
) -> bool:
    """
    Return whether an entry owned by *source_layer* is editable over REST.

    A missing or unrecognised layer (legacy single-root usage) is treated
    as editable. This is the signal callers use (e.g. the web UI) to hide
    edit affordances for read-only (e.g. externally-synced) layers.

    :param layers: Configured layers, base → overlay.
    :param source_layer: Owning layer name, or ``None``.
    :returns: ``True`` when REST writes to the layer are allowed.
    """
    if not source_layer:
        return True
    for layer in layers:
        if layer.name == source_layer:
            return not layer.rest_readonly
    return True


def require_exists(
    name: str, exists: bool, *, not_found: Callable[[str], Exception]
) -> None:
    """
    Raise via *not_found* when *exists* is false.

    A thin "does this name exist" guard: callers compute *exists* against
    whatever merged-or-per-layer view is appropriate for their catalog, so
    this function stays oblivious to how existence is actually determined.

    :param name: The name being checked (passed to *not_found*).
    :param exists: Whether the name was found.
    :param not_found: Exception factory, e.g. ``KitNotFoundError``.
    :raises Exception: Whatever ``not_found(name)`` constructs, when
        *exists* is false.
    """
    if not exists:
        raise not_found(name)
