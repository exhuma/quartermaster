"""
Serve the rendered Sphinx documentation site at ``/docs``.

The documentation is authored under the repository-root ``docs/`` tree and
rendered to static HTML by the docs build stage in ``server/Dockerfile`` (see
also ``task docs`` for a local render). The built HTML is baked into the image
and served here as plain static files — like the SPA (``app.webui``), it is
never runtime-volume content.

``/docs`` is public: it is not under the auth-gated prefixes
(``app.auth._PROTECTED_PREFIXES``), so anyone reaching the instance can read
the docs. When ``settings.docs_dist`` does not exist (local dev, tests) nothing
is mounted and the API/MCP are unaffected.

The mount is registered **before** the SPA history-mode fallback in
``app.main`` so the ``/docs`` sub-app wins routing over the catch-all
``/{full_path:path}`` route (the same ordering the ``/changelog.json`` route
relies on).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import _DOCS_DIST_DEFAULT

logger = logging.getLogger(__name__)


def _dist_dir() -> Path:
    """
    Resolve the docs build directory without constructing Settings.

    Reading the env var directly keeps app construction free of the
    required-settings validation (so the app imports without a full
    environment), mirroring ``app.webui._dist_dir``.

    :returns: The configured (or default) ``docs_dist`` path.
    """
    return Path(os.environ.get("QM_DOCS_DIST", str(_DOCS_DIST_DEFAULT)))


def mount_docs(app: FastAPI) -> None:
    """
    Mount the rendered documentation site at ``/docs`` when a build exists.

    No-op when there is no build (local dev, tests). Must be called before the
    SPA fallback in ``app.main`` so the mount is matched ahead of the catch-all
    route.

    :param app: The FastAPI application.
    """
    dist = _dist_dir()
    if not (dist / "index.html").is_file():
        logger.info("Docs site not mounted: no build at %s", dist)
        return

    # ``html=True`` serves ``index.html`` for directory paths (e.g. ``/docs/``
    # and every Sphinx section directory), matching Sphinx's relative links.
    app.mount(
        "/docs",
        StaticFiles(directory=dist, html=True),
        name="docs",
    )
    logger.info("Docs site mounted from %s", dist)
