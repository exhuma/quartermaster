"""Cross-cutting HTTP middleware (module-http-middleware-hardening).

Three dedicated middlewares applied to every request/response:

- :class:`RequestLoggingMiddleware` — assigns/propagates a correlation ID via a
  contextvar, emits one structured log line per request, echoes the ID back,
  and clears it in all code paths.
- :class:`SecurityHeadersMiddleware` — sets the three mandatory security
  headers on every response.
- :class:`VersionHeaderMiddleware` — stamps ``X-Quartermaster-Version`` (the
  version is injected at construction, never read from global state here).

Registration order lives in :func:`app.main.create_app`; see the LIFO comment
there. These are framework-specific realisations of framework-neutral rules.
"""

from __future__ import annotations

import logging
import time
import uuid

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import Response

from app.logging_config import clear_correlation_id, set_correlation_id

logger = logging.getLogger(__name__)

CORRELATION_ID_HEADER = "X-Correlation-ID"
VERSION_HEADER = "X-Quartermaster-Version"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Correlation-ID propagation + one structured log line per request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        cid = request.headers.get(CORRELATION_ID_HEADER) or str(uuid.uuid4())
        client = request.client.host if request.client else "unknown"
        start = time.monotonic()
        set_correlation_id(cid)
        try:
            response = await call_next(request)
        except Exception:
            logger.exception(
                "%s %s from %s failed after %.1f ms",
                request.method,
                request.url.path,
                client,
                (time.monotonic() - start) * 1000,
            )
            clear_correlation_id()
            raise
        logger.info(
            "%s %s from %s -> %d (%.1f ms)",
            request.method,
            request.url.path,
            client,
            response.status_code,
            (time.monotonic() - start) * 1000,
        )
        response.headers[CORRELATION_ID_HEADER] = cid
        clear_correlation_id()
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set the three mandatory security headers on every response."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = (
            "strict-origin-when-cross-origin"
        )
        return response


class VersionHeaderMiddleware(BaseHTTPMiddleware):
    """Stamp the application version on every response."""

    def __init__(self, app: object, version: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._version = version

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        response.headers[VERSION_HEADER] = self._version
        return response
