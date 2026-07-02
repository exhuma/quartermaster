"""Pluggable maintainer-notification backends for kit-extension gap reports.

Backend selection is driven by ``settings.issue_backend`` (``"github"`` |
``"gitlab"`` | ``"none"``). When unset, defaults to GitHub for back-compat
with deployments that only configured ``GITHUB_*`` settings.
"""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.notifications.base import (
    GapReport,
    IssueBackend,
    IssueRef,
    normalize_report,
)
from app.notifications.github import GitHubBackend
from app.notifications.gitlab import GitLabBackend

__all__ = [
    "check_existing_kit_extension_issue",
    "gap_tools_enabled",
    "get_issue_backend",
    "request_kit_extension",
]


def _select_backend(settings: Any) -> IssueBackend:
    """Return the backend selected by *settings*.

    :raises ValueError: If no backend is selected/configured, or the
        selected backend is missing required settings.
    """
    name = (
        getattr(settings, "issue_backend", None) or ""
    ).strip().lower() or "github"
    if name == "none":
        raise ValueError("Issue backend disabled (QM_ISSUE_BACKEND=none).")
    if name == "github":
        return GitHubBackend.from_settings(settings)
    if name == "gitlab":
        return GitLabBackend.from_settings(settings)
    raise ValueError(f"Unknown issue backend: {name!r}")


def get_issue_backend(settings: Any = None) -> IssueBackend | None:
    """Return the configured backend, or ``None`` when unconfigured.

    Tolerates a missing/incomplete configuration (returns ``None`` instead
    of raising) so it is safe to call for feature-gating (e.g. deciding
    whether to register the gap-filing MCP tools) even when required
    Keycloak settings are absent (e.g. during test collection).
    """
    from pydantic import ValidationError

    try:
        resolved_settings = settings if settings is not None else get_settings()
    except ValidationError:
        return None
    try:
        return _select_backend(resolved_settings)
    except ValueError:
        return None


def gap_tools_enabled(settings: Any = None) -> bool:
    """Return whether a maintainer-notification backend is configured."""
    return get_issue_backend(settings) is not None


def _report_dict(report: GapReport) -> dict[str, Any]:
    return {
        "title": report.title,
        "summary": report.summary,
        "discovered_traits": report.discovered_traits,
        "missing_tools": report.missing_tools,
        "details": report.details,
    }


def _issue_dict(ref: IssueRef) -> dict[str, Any]:
    owner, _, repo = ref.project.partition("/")
    return {
        "owner": owner,
        "repo": repo,
        "number": ref.number,
        "url": ref.url,
        "title": ref.title,
        "state": ref.state,
    }


def check_existing_kit_extension_issue(
    *,
    title: str,
    summary: str,
    discovered_traits: list[str] | None = None,
    missing_tools: list[str] | None = None,
    details: str | None = None,
) -> dict[str, Any]:
    """Check whether a matching open issue already exists."""
    report = normalize_report(
        title=title,
        summary=summary,
        discovered_traits=discovered_traits,
        missing_tools=missing_tools,
        details=details,
    )
    backend = _select_backend(get_settings())
    existing = backend.find_existing(report)

    return {
        "exists": existing is not None,
        "request": _report_dict(report),
        "issue": _issue_dict(existing) if existing is not None else None,
    }


def request_kit_extension(
    *,
    title: str,
    summary: str,
    discovered_traits: list[str] | None = None,
    missing_tools: list[str] | None = None,
    details: str | None = None,
) -> dict[str, Any]:
    """
    Accept extension/clarification requests and create an issue.

    :raises ValueError: If title or summary is empty, or the backend fails.
    """
    report = normalize_report(
        title=title,
        summary=summary,
        discovered_traits=discovered_traits,
        missing_tools=missing_tools,
        details=details,
    )
    backend = _select_backend(get_settings())
    existing = backend.find_existing(report)
    if existing is not None:
        return {
            "status": "duplicate",
            "message": f"Matching {backend.name} issue already exists.",
            "request": _report_dict(report),
            "issue": _issue_dict(existing),
        }

    created = backend.create(report)
    return {
        "status": "created",
        "message": f"Request materialized as {backend.name} issue.",
        "request": _report_dict(report),
        "issue": _issue_dict(created),
    }
