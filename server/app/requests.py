"""Backward-compatible re-export of the kit-extension request seam.

The implementation lives in :mod:`app.notifications` (backend-agnostic
``IssueBackend`` protocol + GitHub/GitLab implementations). This module is
kept so existing imports (``from app.requests import ...``) keep working.
"""

from __future__ import annotations

from app.notifications import (
    check_existing_kit_extension_issue,
    request_kit_extension,
)

__all__ = [
    "check_existing_kit_extension_issue",
    "request_kit_extension",
]
