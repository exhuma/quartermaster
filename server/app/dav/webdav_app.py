"""
Embedded WebDAV endpoint for authoring the kit catalog.

Mounts a ``wsgidav`` filesystem provider (bridged to ASGI via ``a2wsgi``)
over the **same** kit roots the MCP reads — so a file written through a
mounted drive is visible to the next ``get_kit`` call with no restart (kit
reads are uncached). Cross-OS native mounting (macOS Finder, Windows
"Map network drive", Linux GVfs/davfs2) plus ``rclone`` as a fallback.

Authentication is handled **upstream** by ``JWTAuthMiddleware`` (HTTP Basic
``username:app-token`` on the ``/dav`` prefix), so wsgidav itself runs with
anonymous access — it never sees credentials it would need to validate.

**Single-layer mode** (``QM_KITS_ROOT`` only):
  The catalog is exposed at ``/dav/`` — the same URL structure as before.

**Multi-layer mode** (``QM_KIT_LAYERS_FILE`` TOML or ``QM_KIT_LAYERS`` JSON):
  Each named layer is exposed at ``/dav/{layer_name}/``.  The bare
  ``/dav/`` collection lists the layer names (wsgidav virtual root).

Layer resolution mirrors :class:`app.config.Settings` precedence
(``QM_KIT_LAYERS_FILE`` → ``QM_KITS_ROOT``) and reuses the same TOML parser,
so the file schema is defined in exactly one place. The env is read directly
(rather than via a full ``Settings``) so mounting ``/dav`` at import time does
not force validation of unrelated settings.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from a2wsgi import WSGIMiddleware
from fastapi import FastAPI
from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

from app.config import load_layers_from_toml

logger = logging.getLogger(__name__)

DAV_MOUNT_PATH = "/dav"


def _resolve_layers() -> list[tuple[str, Path, bool]]:
    """
    Resolve kit layers from the environment for WebDAV mounting.

    Returns a list of ``(name, path, readonly)`` tuples, following the same
    precedence as :class:`app.config.Settings`:
    ``QM_KIT_LAYERS_FILE`` (TOML) → ``QM_KITS_ROOT`` (single catalog).

    :raises RuntimeError: If no usable kit-catalog env var is set.
    """
    layers_file = os.environ.get("QM_KIT_LAYERS_FILE")
    if layers_file:
        layers = load_layers_from_toml(Path(layers_file))
        return [
            (layer.name, layer.path, layer.readonly) for layer in layers
        ]

    kits_root = os.environ.get("QM_KITS_ROOT")
    if kits_root:
        return [("default", Path(kits_root), False)]

    raise RuntimeError(
        "No kit catalog configured for WebDAV. Set either "
        "QM_KIT_LAYERS_FILE or QM_KITS_ROOT "
        "(a local checkout in dev, or the mounted volume in production, "
        "e.g. /data/kits) — the catalog is not bundled with this server."
    )


def build_dav_asgi(
    layers: list[tuple[str, Path, bool]],
    mount_path: str = DAV_MOUNT_PATH,
) -> WSGIMiddleware:
    """
    Build the WebDAV ASGI application over one or more kit layers.

    In single-layer mode (one entry named ``"default"`` from
    ``QM_KITS_ROOT``), the provider is mounted at ``"/"`` so the URL
    structure is identical to the pre-layering layout (``/dav/<kit>/``).

    In multi-layer mode, each layer is mounted at ``"/{name}/"`` within
    the WebDAV namespace, so each layer's kits appear under
    ``/dav/{layer_name}/<kit>/``.

    :param layers: Ordered list of ``(name, path, readonly)`` tuples.
    :param mount_path: URL prefix the app is mounted under. wsgidav uses
        this to emit correctly-prefixed ``href``\\s in ``PROPFIND``
        responses.
    :returns: An ASGI app (wsgidav wrapped by a2wsgi).
    """
    if len(layers) == 1 and layers[0][0] == "default":
        name, path, readonly = layers[0]
        provider_mapping: dict[str, FilesystemProvider] = {
            "/": FilesystemProvider(str(path), readonly=readonly)
        }
    else:
        provider_mapping = {
            f"/{name}/": FilesystemProvider(str(path), readonly=readonly)
            for name, path, readonly in layers
        }

    config = {
        "provider_mapping": provider_mapping,
        "mount_path": mount_path,
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

    Reads layer configuration from the environment; see module docstring
    for URL mapping in single- vs multi-layer mode.

    :param app: The FastAPI application.
    """
    layers = _resolve_layers()
    # a2wsgi's WSGIMiddleware is a valid ASGI app at runtime; Starlette's
    # mount() type hint does not recognise the bridged WSGI callable.
    app.mount(DAV_MOUNT_PATH, build_dav_asgi(layers))  # type: ignore[arg-type]
    if len(layers) == 1 and layers[0][0] == "default":
        logger.info(
            "WebDAV authoring mounted at %s over %s",
            DAV_MOUNT_PATH,
            layers[0][1],
        )
    else:
        for name, path, readonly in layers:
            logger.info(
                "WebDAV layer %r mounted at %s/%s/ over %s (readonly=%s)",
                name,
                DAV_MOUNT_PATH,
                name,
                path,
                readonly,
            )
