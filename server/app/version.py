"""Single source for the version the running app reports.

Both surfaces that expose a version — the ``X-Quartermaster-Version`` response
header (``app/middleware.py``) and the OpenTelemetry ``service.version``
resource attribute (``app/telemetry.py``) — resolve it here, so they can never
drift.

Resolution order:

1. ``QM_APP_VERSION`` — injected at release-image build time from the git tag
   (see ``server/Dockerfile``); the frontend is fed the same value as
   ``VITE_APP_VERSION`` so the SPA and the API report the same string.
2. Installed package metadata (``quartermaster``) — the dev/local path.
3. ``"0.0.0"`` placeholder — only if the package is not installed.

The ``pyproject.toml`` / ``package.json`` version stays a dev placeholder; the
real release version is supplied at build time rather than committed.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

_PLACEHOLDER = "0.0.0"


def app_version() -> str:
    """Return the version the app should report (env override → metadata)."""
    override = os.environ.get("QM_APP_VERSION", "").strip()
    if override:
        return override
    try:
        return _pkg_version("quartermaster")
    except PackageNotFoundError:  # pragma: no cover - always installed
        return _PLACEHOLDER
