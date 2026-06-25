"""
Embedded WebDAV endpoint for authoring the kit catalog.

Mounts a ``wsgidav`` filesystem provider (bridged to ASGI via ``a2wsgi``)
over the **same** ``kits_root`` the MCP reads — so a file written through a
mounted drive is visible to the next ``get_kit`` call with no restart (kit
reads are uncached). Cross-OS native mounting (macOS Finder, Windows
"Map network drive", Linux GVfs/davfs2) plus ``rclone`` as a fallback.

Authentication is handled **upstream** by ``JWTAuthMiddleware`` (HTTP Basic
``username:app-token`` on the ``/dav`` prefix), so wsgidav itself runs with
anonymous access — it never sees credentials it would need to validate.

The kit catalog directory is resolved from the ``KITS_ROOT`` environment
variable (the production knob), mirroring ``app.webui`` so app construction
does not require a fully-validated Settings object.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

logger = logging.getLogger(__name__)

DAV_MOUNT_PATH = "/dav"


def _kits_root() -> Path:
    """
    Resolve the kit catalog root from the environment.

    ``KITS_ROOT`` is required — the catalog is external and never bundled
    with the server. Read directly from the environment (rather than the
    full ``Settings``) so mounting ``/dav`` at import time does not force
    validation of unrelated settings.

    :raises RuntimeError: If ``KITS_ROOT`` is unset or empty.
    """
    root = os.environ.get("KITS_ROOT")
    if not root:
        raise RuntimeError(
            "KITS_ROOT is not set. Point it at your kit catalog "
            "(a local checkout in dev, or the mounted volume in production, "
            "e.g. /data/kits) — the catalog is not bundled with this server."
        )
    return Path(root)


def build_dav_asgi(kits_root: Path) -> WSGIMiddleware:
    """
    Build the WebDAV ASGI application over *kits_root*.

    :param kits_root: Directory to expose read/write over WebDAV.
    :returns: An ASGI app (wsgidav wrapped by a2wsgi).
    """
    provider = FilesystemProvider(str(kits_root), readonly=False)
    config = {
        "provider_mapping": {"/": provider},
        # Anonymous: authentication is enforced upstream in the FastAPI
        # middleware (Basic username:app-token on /dav).
        "simple_dc": {"user_mapping": {"*": True}},
        "verbose": 0,
        "logging": {"enable": False},
        "dir_browser": {"enable": False},
    }
    return WSGIMiddleware(WsgiDAVApp(config))


def mount_dav(app: FastAPI) -> None:
    """
    Mount the WebDAV app at ``/dav`` over the configured kit catalog.

    :param app: The FastAPI application.
    """
    kits_root = _kits_root()
    app.mount(DAV_MOUNT_PATH, build_dav_asgi(kits_root))
    logger.info(
        "WebDAV authoring mounted at %s over %s", DAV_MOUNT_PATH, kits_root
    )
