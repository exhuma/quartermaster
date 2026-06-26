"""Shared pytest fixtures and test-session environment setup."""

from __future__ import annotations

import os
import tempfile

# The kit catalog is external and QM_KITS_ROOT is required (no in-repo
# fallback). app.main builds the app — including the /dav mount, which
# reads QM_KITS_ROOT — at import time, so provide a throwaway catalog dir for
# the whole session before any test module imports the app. Individual
# tests still override QM_KITS_ROOT via monkeypatch as needed.
os.environ.setdefault(
    "QM_KITS_ROOT", tempfile.mkdtemp(prefix="quartermaster-test-kits-")
)
