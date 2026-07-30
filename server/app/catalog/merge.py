"""Generic layered directory-catalog merge: whole-name shadowing.

Implements the "iterate layers low → high priority; the highest-priority
layer that contains a name owns *all* of that name's contributed entries"
merge rule shared by every layered catalog. Generic over what per-name
*entries* mean (for kits today, a ``version -> index_path`` map) — this
module treats them as an opaque value and never interprets them.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.config import KitLayerConfig


def scan_layers_merged[EntriesT](
    layers: list[KitLayerConfig],
    scan_root: Callable[[Path], dict[str, EntriesT]],
) -> dict[str, tuple[EntriesT, Path, str]]:
    """
    Scan every layer and merge with whole-name shadowing.

    Iterates *layers* from lowest to highest priority. When the same name
    appears in multiple layers, the highest-priority layer that contains it
    owns **all** of that name's entries (whole-name shadowing) — a
    lower-priority layer's entries for that name are dropped entirely, not
    merged field-by-field.

    :param layers: Ordered list of layers, base (index 0) → overlay (last).
    :param scan_root: Callable returning ``{name: entries}`` for one layer's
        root directory. *entries* is opaque to this function — whatever
        *scan_root* returns for the winning layer is passed through as-is.
    :returns: Mapping of name → ``(entries, layer_root, layer_name)``,
        sorted by name, where *entries*/*layer_root*/*layer_name* all come
        from whichever layer owns that name.
    """
    merged: dict[str, tuple[EntriesT, Path, str]] = {}
    for layer in layers:
        for name, entries in scan_root(layer.path).items():
            merged[name] = (entries, layer.path, layer.name)
    return {name: merged[name] for name in sorted(merged)}
