"""
Serve the built single-page web UI and its runtime configuration.

Following the module-runtime-config-spa kit, the SPA is built **once** and
configured **at runtime**: this server renders ``/config.js`` from its own
settings (instead of an nginx + envsubst entrypoint), and the SPA reads the
injected ``window.__APP_CONFIG__`` global. Only public, non-secret values
are exposed (the Keycloak authority, the public client id, redirect URIs).

The shell, its assets, and ``/config.js`` are public (see ``app.auth``):
the SPA is static JavaScript that authenticates against Keycloak via OIDC,
so it must load before any token exists. Only ``/api`` and ``/kits`` are
protected. When ``settings.webui_dist`` does not exist (local dev, tests)
nothing is mounted and the API/MCP are unaffected.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app.config import _WEBUI_DIST_DEFAULT, Settings, get_settings

logger = logging.getLogger(__name__)


def _dist_dir() -> Path:
    """
    Resolve the web-UI build directory without constructing Settings.

    Reading the env var directly keeps app construction free of the
    required-settings validation (so the app imports without a full
    environment); request-time handlers still use ``get_settings()``.

    :returns: The configured (or default) ``webui_dist`` path.
    """
    return Path(os.environ.get("QM_WEBUI_DIST", str(_WEBUI_DIST_DEFAULT)))


def runtime_config(settings: Settings) -> dict[str, Any]:
    """
    Build the public runtime-config payload for the SPA.

    :param settings: Application settings.
    :returns: The ``window.__APP_CONFIG__`` shape (public values only).
    """
    origin = settings.server_origin
    return {
        "oidcAuthority": settings.keycloak_issuer,
        "oidcClientId": settings.webui_keycloak_client_id,
        "oidcRedirectUri": f"{origin}/auth/callback",
        "oidcPostLogoutUri": f"{origin}/",
        "oidcScope": " ".join(settings.oauth_scopes),
        # Same-origin: the SPA calls relative ``/api`` paths.
        "apiBaseUrl": "",
    }


def render_config_js(settings: Settings) -> str:
    """
    Render the ``config.js`` script that injects the runtime global.

    :param settings: Application settings.
    :returns: JavaScript assigning ``window.__APP_CONFIG__``.
    """
    payload = json.dumps(runtime_config(settings), indent=2)
    return f"window.__APP_CONFIG__ = {payload};\n"


def mount_webui(app: FastAPI) -> None:
    """
    Mount the SPA, its assets, and ``/config.js`` when a build exists.

    No-op when there is no build (local dev, tests). Does not construct
    ``Settings`` at call time — the ``/config.js`` handler reads settings
    lazily per request.

    :param app: The FastAPI application.
    """
    dist = _dist_dir()
    index_file = dist / "index.html"
    if not index_file.is_file():
        logger.info("Web UI not mounted: no build at %s", dist)
        return

    assets_dir = dist / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_dir),
            name="webui-assets",
        )

    @app.get("/config.js", include_in_schema=False)
    async def config_js() -> Response:
        return Response(
            content=render_config_js(get_settings()),
            media_type="application/javascript",
            headers={"Cache-Control": "no-store"},
        )

    async def _serve_index() -> FileResponse:
        return FileResponse(index_file, headers={"Cache-Control": "no-store"})

    app.add_api_route(
        "/", _serve_index, methods=["GET"], include_in_schema=False
    )

    # SPA history-mode fallback: any other non-API/MCP path returns the
    # shell so client-side routes survive a full-page refresh. API and MCP
    # paths are excluded so an unknown one still yields a real 404.
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith(("api/", "kits/")) or full_path in (
            "api",
            "kits",
        ):
            raise HTTPException(status_code=404)
        return FileResponse(
            index_file, headers={"Cache-Control": "no-store"}
        )

    logger.info("Web UI mounted from %s", dist)
