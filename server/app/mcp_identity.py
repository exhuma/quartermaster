"""ASGI wrapper that carries caller identity into the mounted FastMCP app.

:class:`~app.auth.JWTAuthMiddleware` resolves the caller and writes
``auth_sub``/``auth_label`` onto ``request.state`` — which Starlette backs with
``scope["state"]``. That dict is preserved when the router dispatches into a
mounted sub-app, so this wrapper (installed **at** the ``/kits`` mount) can read
it and bind the identity context variables in the *same task* that will run the
tool.

Why a plain ASGI wrapper and not ``BaseHTTPMiddleware``: the latter runs its
downstream in a separate anyio task, so any :class:`~contextvars.ContextVar`
set inside ``dispatch`` does not reliably reach a mounted sub-app. Setting the
contextvar here — right before delegating to the wrapped app — keeps it in the
task the FastMCP tool executes in, so ``app.identity.current_sub()`` is visible
inside ``@mcp.tool`` functions.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.identity import reset_identity, set_identity


class MCPIdentityASGI:
    """Bind caller identity from ``scope["state"]`` around the wrapped app."""

    def __init__(self, app: ASGIApp) -> None:
        """
        :param app: The mounted ASGI application (the FastMCP streamable-HTTP
            app) to delegate to once identity is bound.
        """
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        """Set identity contextvars for HTTP requests, then delegate.

        Non-HTTP scopes (``lifespan``, ``websocket``) pass straight through so
        the wrapped app's own lifespan/handshake handling is untouched.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = scope.get("state") or {}
        tokens = set_identity(state.get("auth_sub"), state.get("auth_label"))
        try:
            await self.app(scope, receive, send)
        finally:
            reset_identity(tokens)
