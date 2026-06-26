"""MCP tool-call audit logging.

A FastMCP :class:`~fastmcp.server.middleware.middleware.Middleware` that emits
one structured log line per ``tools/call`` and one per session ``initialize``.

Why this exists: Quartermaster's intended UX is that *every* coding-task prompt
makes the agent engage this MCP (discover traits → select kits → load sections).
Whether that actually happens is a host decision the server cannot force, and
until now the server had **no** visibility into it — the ASGI-layer logs
(:mod:`app.auth`, :mod:`app.user_agent`) see ``POST /kits/mcp`` as one opaque
request and cannot tell which tool was called.

This middleware closes that gap. The server cannot see user prompts, but it
sees exactly one ``initialize`` per session plus the ordered ``tools/call``
invocations within it. Correlating by ``session`` and ``seq`` lets you compute
the metric that confirms or refutes the "agents aren't engaging" hunch:
sessions that initialize but never call a discovery/load tool.

Log emission never raises into the tool path — a broken logger must not break a
tool call.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from fastmcp.server.middleware.middleware import Middleware, MiddlewareContext

logger = logging.getLogger("app.mcp_audit")


def _safe_attr(obj: Any, name: str) -> Any:
    """Read *name* off *obj*, returning ``None`` instead of raising.

    FastMCP context accessors (``session_id`` etc.) can raise when no request
    context is active; audit logging must degrade quietly rather than fail.
    """
    try:
        return getattr(obj, name, None)
    except Exception:  # pragma: no cover - defensive
        return None


class ToolCallAuditMiddleware(Middleware):
    """Log MCP session starts and per-session tool-call sequences.

    Records are plain ``logger.info`` lines tagged ``mcp_audit`` with
    ``key=value`` fields so they are greppable without a log pipeline:

    - ``mcp_audit event=initialize session=<id> client=<id>``
    - ``mcp_audit event=tool_call session=<id> seq=<n> client=<id>
      tool=<name> ok=<bool> duration_ms=<float>``

    The per-session sequence counter is in-memory (per process); it resets on
    restart, which is fine for the engagement metric (sessions are short-lived).
    """

    def __init__(self) -> None:
        self._seq: dict[str, int] = {}

    def _next_seq(self, session_id: str | None) -> int:
        """Return the next 1-based call index for *session_id*."""
        key = session_id or "-"
        nxt = self._seq.get(key, 0) + 1
        self._seq[key] = nxt
        return nxt

    async def on_initialize(
        self,
        context: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[Any]],
    ) -> Any:
        """Emit a session-start record, then delegate."""
        ctx = context.fastmcp_context
        try:
            logger.info(
                "mcp_audit event=initialize session=%s client=%s",
                _safe_attr(ctx, "session_id"),
                _safe_attr(ctx, "client_id"),
            )
        except Exception:  # pragma: no cover - logging never breaks the call
            pass
        return await call_next(context)

    async def on_call_tool(
        self,
        context: MiddlewareContext,
        call_next: Callable[[MiddlewareContext], Awaitable[Any]],
    ) -> Any:
        """Emit a tool-call record (name + per-session seq + outcome)."""
        ctx = context.fastmcp_context
        session_id = _safe_attr(ctx, "session_id")
        tool_name = _safe_attr(context.message, "name")
        seq = self._next_seq(session_id)
        started = time.perf_counter()
        ok = True
        try:
            return await call_next(context)
        except Exception:
            ok = False
            raise
        finally:
            try:
                logger.info(
                    "mcp_audit event=tool_call session=%s seq=%d client=%s "
                    "tool=%s ok=%s duration_ms=%.1f",
                    session_id,
                    seq,
                    _safe_attr(ctx, "client_id"),
                    tool_name,
                    ok,
                    (time.perf_counter() - started) * 1000.0,
                )
            except Exception:  # pragma: no cover - logging must not break
                pass
