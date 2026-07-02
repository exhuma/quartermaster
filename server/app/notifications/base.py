"""Backend-agnostic types and helpers for kit-extension gap reports.

Shared by every :class:`IssueBackend` implementation so dedupe semantics
(title/body matching) and issue formatting stay identical across backends.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class GapReport:
    """A normalized, backend-agnostic kit-extension/gap request."""

    title: str
    summary: str
    discovered_traits: list[str] = field(default_factory=list)
    missing_tools: list[str] = field(default_factory=list)
    details: str | None = None


@dataclass(frozen=True)
class IssueRef:
    """Backend-agnostic projection of a materialized or found issue."""

    backend: str
    project: str
    number: int | None
    url: str | None
    title: str | None
    state: str | None


class IssueBackend(Protocol):
    """A maintainer-notification backend that can file/dedupe gap issues."""

    name: str

    def find_existing(self, report: GapReport) -> IssueRef | None:
        """Return an existing open issue matching *report*, if any."""
        ...

    def create(self, report: GapReport) -> IssueRef:
        """Create a new issue for *report* and return its reference."""
        ...


def normalize_issue_title(title: str) -> str:
    """Normalize a title for tolerant comparison (case/whitespace only)."""
    return re.sub(r"\s+", " ", title.strip().lower())


def normalize_list(values: list[str] | None) -> list[str]:
    """Normalize list input values into lowercase unique entries."""
    if not values:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def normalize_report(
    *,
    title: str,
    summary: str,
    discovered_traits: list[str] | None,
    missing_tools: list[str] | None,
    details: str | None,
) -> GapReport:
    """Normalize and validate a raw request into a :class:`GapReport`."""
    normalized_title = title.strip()
    normalized_summary = summary.strip()
    if not normalized_title:
        raise ValueError("title must not be empty")
    if not normalized_summary:
        raise ValueError("summary must not be empty")

    return GapReport(
        title=normalized_title,
        summary=normalized_summary,
        discovered_traits=normalize_list(discovered_traits),
        missing_tools=normalize_list(missing_tools),
        details=(details or "").strip() or None,
    )


def build_issue_title(title: str) -> str:
    """Build the canonical issue title for extension requests."""
    return f"[Kit Request] {title}"


def build_issue_body(report: GapReport) -> str:
    """Build a deterministic issue body from a normalized report."""
    traits_line = (
        ", ".join(report.discovered_traits)
        if report.discovered_traits
        else "none"
    )
    tools_line = (
        ", ".join(report.missing_tools) if report.missing_tools else "none"
    )
    details_block = (
        report.details
        if report.details
        else "No additional details provided."
    )

    return (
        "## Kit Extension Request\n\n"
        f"**Summary**\n{report.summary}\n\n"
        f"**Discovered Traits**\n{traits_line}\n\n"
        f"**Missing Tools**\n{tools_line}\n\n"
        f"**Details**\n{details_block}"
    )


def http_request_json(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    json: dict[str, Any] | None = None,
    timeout: float = 10,
) -> Any:
    """Perform an HTTP request and parse the JSON response.

    Shared by every backend so network/HTTP-status errors are wrapped into
    ``ValueError`` identically regardless of which issue tracker is in use.
    """
    try:
        response = httpx.request(
            method,
            url,
            headers=headers,
            json=json,
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        body_text = exc.response.text.strip() or "<empty response body>"
        raise ValueError(
            "Issue backend request failed with status "
            f"{exc.response.status_code}: {body_text}"
        ) from exc
    except httpx.HTTPError as exc:
        raise ValueError(
            f"Issue backend request failed due to network error: {exc}"
        ) from exc
