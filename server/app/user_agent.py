"""
Registered-User-Agent gate for client identification.

Every authenticated request must come from an identifiable client:

- **Browsers** (the web UI) send a ``User-Agent`` starting with
  ``Mozilla/…`` and are allowed by default — browsers cannot set a custom
  ``User-Agent`` from JavaScript, so the SPA is identified by its OIDC
  client instead.
- **Programmatic clients** (scripts hitting the REST API) send a custom
  ``User-Agent`` and must register it first via ``POST /api/clients``. An
  unregistered custom ``User-Agent`` is refused with **403** and a pointer
  to the registration route.

The gate covers **only the REST API** (``/api``). The MCP endpoint, the
health probe, the OAuth well-known documents, the Swagger docs, and the
registration route itself are all exempt. This uniquely identifies REST
clients; it is not a strong security gate (a client may spoof a browser
``User-Agent``).
"""

from __future__ import annotations

import logging
import re

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings
from app.storage import client_registry

logger = logging.getLogger(__name__)

# Browser User-Agents conventionally begin with "Mozilla/<n>" (Chrome,
# Firefox, Safari, Edge all do). Non-browser clients (curl, httpx, node,
# coding-agent SDKs) do not, so they fall through to the registry check.
_BROWSER_UA_RE = re.compile(r"^Mozilla/\d", re.IGNORECASE)

# The self-service registration route is exempt from the gate (a client
# must be able to register before it is known). Matched as (method, path).
_REGISTRATION_ROUTE = ("POST", "/api/clients")

# Swagger UI + its schema live under ``/api`` (so the root ``/docs`` is free
# for the rendered docs site) but must stay reachable by any client — Swagger
# was UA-exempt when it served from ``/docs``, and OpenAPI generators fetch the
# schema without a browser User-Agent. Exempt both explicitly.
_SWAGGER_PATHS = frozenset({"/api/docs", "/api/openapi.json"})


def _is_exempt(method: str, path: str) -> bool:
    """
    Return whether a request bypasses the User-Agent gate.

    The gate covers only the REST API, so anything outside ``/api`` (the
    MCP mount, health, well-known docs) is exempt, as are the Swagger docs
    and the self-service registration route.

    :param method: HTTP method.
    :param path: Request path.
    :returns: ``True`` if the request bypasses the gate.
    """
    if not path.startswith("/api/"):
        return True
    if path in _SWAGGER_PATHS:
        return True
    return (method, path) == _REGISTRATION_ROUTE


class UserAgentMiddleware(BaseHTTPMiddleware):
    """Refuse requests from unregistered, non-browser User-Agents."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Allow browsers and registered clients; refuse the rest.

        :param request: Incoming request.
        :param call_next: Downstream handler.
        :returns: The downstream response, or ``403`` for an
            unrecognised client.
        """
        if _is_exempt(request.method, request.url.path):
            return await call_next(request)

        user_agent = request.headers.get("user-agent", "")
        if _BROWSER_UA_RE.match(user_agent):
            return await call_next(request)

        settings = get_settings()
        if client_registry.is_registered(
            settings.client_registry_path, user_agent
        ):
            return await call_next(request)

        logger.info("Refused unregistered User-Agent: %r", user_agent)
        register_url = f"{settings.server_origin}/api/clients"
        return JSONResponse(
            status_code=403,
            content={
                "detail": (
                    "Unrecognised client. Register your User-Agent with "
                    f"POST {register_url} (see /api/docs), then retry. Browser "
                    "clients are allowed automatically."
                )
            },
        )
