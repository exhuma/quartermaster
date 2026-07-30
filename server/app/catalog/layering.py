"""Generic layer resolution for a layered directory catalog.

Combines a catalog's configured public layers with an optional per-caller
private overlay, appended last (highest priority) so a private entry shadows
a public entry of the same name **for the owner only**.

Nothing here knows about kits specifically: callers pass in their own
public ``base_layers`` and a ``private_roots_fn`` (e.g.
``app.private_kits.owned_private_roots``) that maps a subject to that
caller's existing private root(s).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.config import KitLayerConfig
from app.identity import current_sub

# The synthetic layer name for a caller's private overlay. One private layer
# at most per caller, placed at highest priority so a private entry shadows
# a public entry of the same name FOR THE OWNER ONLY.
PRIVATE_LAYER_NAME = "__private__"

# Sentinel distinguishing "resolve the subject from the identity contextvar"
# (the default for owner-aware reads) from an explicit ``None`` meaning
# "public catalog only, ignore any caller in context" (used by paths that
# must never let per-caller private content poison a shared cache).
CTX_SUBJECT: Any = object()


def resolve_subject(subject: Any) -> str | None:
    """Resolve a subject argument to a concrete subject or ``None``.

    :param subject: ``CTX_SUBJECT`` → read the identity contextvar;
        otherwise a ``str`` subject or ``None`` (public) passed straight
        through.
    """
    if subject is CTX_SUBJECT:
        return current_sub()
    return subject


def caller_layers(
    base_layers: list[KitLayerConfig],
    private_roots_fn: Callable[[str | None], list[Path]],
    subject: Any = CTX_SUBJECT,
) -> list[KitLayerConfig]:
    """Return effective layers for a caller, private overlay last.

    The public layers are always present; when the caller (from *subject*
    or the identity contextvar) has an existing private catalog, it is
    appended as the highest-priority layer. A caller with no private
    entries — or no identity — sees exactly the public layers, so this is a
    no-op on the hot public path and default-deny for private content.

    :param base_layers: The catalog's configured public layers, base →
        overlay.
    :param private_roots_fn: Maps a resolved subject (or ``None``) to that
        caller's existing private root(s), e.g.
        :func:`app.private_kits.owned_private_roots`.
    :param subject: ``CTX_SUBJECT`` (contextvar), a ``str`` subject, or
        ``None`` to force public-only.
    :returns: Ordered layers, base → overlay, private overlay last if any.
    """
    layers = list(base_layers)
    sub = resolve_subject(subject)
    for root in private_roots_fn(sub):
        layers.append(
            KitLayerConfig(name=PRIVATE_LAYER_NAME, path=root, readonly=False)
        )
    return layers
