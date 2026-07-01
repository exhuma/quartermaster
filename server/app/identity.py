"""Per-request caller identity, propagated via context variables.

The authenticated caller's stable subject (`sub`) and a human-readable label
are resolved by :class:`~app.auth.JWTAuthMiddleware` and stored on
``request.state``. REST route handlers can read them directly from the request,
but the FastMCP tool functions mounted at ``/kits/mcp`` never receive the
Starlette ``Request`` — so identity must reach them another way.

This module holds that channel: a pair of :class:`~contextvars.ContextVar`
values that :class:`~app.mcp_identity.MCPIdentityASGI` sets **in the same task
that runs the tool** (a plain-ASGI wrapper at the mount, not a
``BaseHTTPMiddleware`` whose downstream runs in a separate task where the
contextvar would not propagate). Kit discovery/read helpers fall back to
:func:`current_sub` so that owner-scoped private kits surface for the caller
without threading a ``subject`` argument through every call site.

Mirrors the correlation-id pattern in :mod:`app.logging_config`, but uses
token-returning ``set``/``reset`` because ASGI apps can nest and each wrapper
must restore exactly the previous value on the way out.
"""

from __future__ import annotations

from contextvars import ContextVar, Token

# The caller's stable, immutable IdP subject (Keycloak ``sub``). ``None``
# outside an authenticated request — callers MUST treat that as "public only".
_auth_sub: ContextVar[str | None] = ContextVar("auth_sub", default=None)
# A human-readable label (preferred_username/email/sub) for UIs and logs.
_auth_label: ContextVar[str | None] = ContextVar("auth_label", default=None)


def set_identity(sub: str | None, label: str | None) -> tuple[Token, Token]:
    """Bind the current task's caller identity.

    :param sub: Stable IdP subject, or ``None`` for an unauthenticated caller.
    :param label: Human-readable label, or ``None``.
    :returns: Reset tokens for :func:`reset_identity`, as ``(sub, label)``.
    """
    return _auth_sub.set(sub), _auth_label.set(label)


def reset_identity(tokens: tuple[Token, Token]) -> None:
    """Restore the identity captured before the matching :func:`set_identity`.

    :param tokens: The ``(sub, label)`` tokens returned by :func:`set_identity`.
    """
    sub_token, label_token = tokens
    _auth_sub.reset(sub_token)
    _auth_label.reset(label_token)


def current_sub() -> str | None:
    """Return the caller's stable subject, or ``None`` outside a request."""
    return _auth_sub.get()


def current_label() -> str | None:
    """Return the caller's display label, or ``None`` outside a request."""
    return _auth_label.get()
