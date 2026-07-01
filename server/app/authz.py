"""Authorization helpers: role lookup, FastAPI dependencies, and exceptions.

The auth *middleware* only proves who the caller is (identity); this module
decides what they may do (roles). It is the single place that reads the role
store so every surface — REST routers, the WebDAV write gate — shares one
definition of "is this caller an editor".
"""

from __future__ import annotations

from fastapi import Request

from app.config import get_settings
from app.storage import role_store


class EditorRequiredError(Exception):
    """Raised when a mutation needs the ``editor`` role the caller lacks."""


class PrivateKitAccessError(Exception):
    """Raised when a caller references a private kit they do not own.

    Mapped to **404** (not 403) so the server never confirms that another
    user's private kit exists.
    """


def is_editor(sub: str | None) -> bool:
    """Return whether *sub* currently resolves to the ``editor`` role.

    Reads settings tolerantly: if configuration is unavailable (e.g. during
    partial test setup) no one is treated as an editor — fail closed.

    :param sub: The caller's stable subject, or ``None``.
    """
    if not sub:
        return False
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - absent config → deny, never crash
        return False
    role = role_store.get_role(
        settings.role_store_path,
        sub,
        initial_editors=settings.initial_editors,
    )
    return role == role_store.EDITOR


def current_subject(request: Request) -> str:
    """FastAPI dependency returning the authenticated caller's stable subject.

    :raises EditorRequiredError: Never; raises nothing on its own beyond the
        401 semantics below.
    :returns: The caller's ``sub``.
    """
    sub = getattr(request.state, "auth_sub", "") or ""
    if not sub:
        # The auth middleware guarantees identity on protected paths; an empty
        # subject here means an unauthenticated or misconfigured caller.
        raise EditorRequiredError("No authenticated user.")
    return sub


def require_editor(request: Request) -> str:
    """FastAPI dependency enforcing the ``editor`` role on catalog mutations.

    :param request: The incoming request (identity on ``request.state``).
    :returns: The caller's ``sub`` when they are an editor.
    :raises EditorRequiredError: When the caller is not an editor (→ 403).
    """
    sub = getattr(request.state, "auth_sub", "") or ""
    if not is_editor(sub):
        raise EditorRequiredError(
            "Editing the shared kit catalog requires the 'editor' role."
        )
    return sub


def current_role(request: Request) -> str:
    """Return the caller's effective role (``editor``/``consumer``)."""
    sub = getattr(request.state, "auth_sub", "") or ""
    return role_store.EDITOR if is_editor(sub) else role_store.CONSUMER
