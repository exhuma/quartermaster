"""Identity plumbing: contextvars + the MCP mount wrapper.

The critical guarantee is that the authenticated caller's ``sub`` — stashed on
``request.state`` (i.e. ``scope["state"]``) by the auth middleware — reaches a
*mounted* sub-app in the task that actually runs its handler, so
``app.identity.current_sub()`` works inside FastMCP tool functions.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.responses import JSONResponse

from app.identity import current_label, current_sub, reset_identity, set_identity
from app.mcp_identity import MCPIdentityASGI


def test_set_reset_identity_round_trip() -> None:
    """set/reset restore exactly the prior value, supporting nesting."""
    assert current_sub() is None
    outer = set_identity("sub-a", "Alice")
    assert current_sub() == "sub-a"
    inner = set_identity("sub-b", "Bob")
    assert current_sub() == "sub-b"
    reset_identity(inner)
    assert current_sub() == "sub-a"
    reset_identity(outer)
    assert current_sub() is None


def test_current_sub_visible_inside_mounted_app() -> None:
    """A mounted app wrapped by MCPIdentityASGI can read the caller's sub.

    This mirrors the production wiring: an outer middleware writes identity to
    ``request.state`` (backed by ``scope["state"]``), the router dispatches
    into the mount, and the wrapper binds the contextvar in the mount's task.
    """
    captured: dict[str, str | None] = {}

    async def _inner(scope, receive, send):  # noqa: ANN001
        # Runs in the mounted task — must observe the bound identity.
        captured["sub"] = current_sub()
        captured["label"] = current_label()
        response = JSONResponse({"ok": True})
        await response(scope, receive, send)

    app = FastAPI()

    @app.middleware("http")
    async def _stash_identity(request: Request, call_next):  # noqa: ANN001
        request.state.auth_sub = "sub-123"
        request.state.auth_label = "Alice"
        return await call_next(request)

    app.mount("/kits", MCPIdentityASGI(_inner))

    client = TestClient(app)
    resp = client.get("/kits/mcp")
    assert resp.status_code == 200
    assert captured == {"sub": "sub-123", "label": "Alice"}


def test_identity_cleared_after_request() -> None:
    """The contextvar does not leak across requests (reset in finally)."""

    async def _inner(scope, receive, send):  # noqa: ANN001
        response = JSONResponse({"sub": current_sub()})
        await response(scope, receive, send)

    app = FastAPI()

    @app.middleware("http")
    async def _stash_identity(request: Request, call_next):  # noqa: ANN001
        request.state.auth_sub = "ephemeral"
        return await call_next(request)

    app.mount("/kits", MCPIdentityASGI(_inner))
    client = TestClient(app)
    assert client.get("/kits/mcp").json() == {"sub": "ephemeral"}
    # Outside any request the module-level contextvar is back to None.
    assert current_sub() is None
