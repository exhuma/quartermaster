"""Request handlers for kit/tool extension workflows."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib import error, request
from urllib.parse import urlencode

from app.config import get_settings


def _normalize_issue_title(title: str) -> str:
    """
    Normalize an issue title for tolerant comparison.

    Lowercases, strips, and collapses internal whitespace so that titles
    differing only in case or spacing still match during deduplication.
    """
    return re.sub(r"\s+", " ", title.strip().lower())


def _normalize_list(values: list[str] | None) -> list[str]:
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


def _normalize_request_payload(
    *,
    title: str,
    summary: str,
    discovered_traits: list[str] | None,
    missing_tools: list[str] | None,
    details: str | None,
) -> dict[str, Any]:
    """Normalize and validate request payload fields."""
    normalized_title = title.strip()
    normalized_summary = summary.strip()
    if not normalized_title:
        raise ValueError("title must not be empty")
    if not normalized_summary:
        raise ValueError("summary must not be empty")

    return {
        "title": normalized_title,
        "summary": normalized_summary,
        "discovered_traits": _normalize_list(discovered_traits),
        "missing_tools": _normalize_list(missing_tools),
        "details": (details or "").strip() or None,
    }


def _build_issue_title(title: str) -> str:
    """Build a canonical GitHub issue title for extension requests."""
    return f"[Kit Request] {title}"


def _require_github_issue_config() -> tuple[str, str, str, str | None]:
    """Return validated GitHub issue settings required for issue creation."""
    settings = get_settings()
    owner = (settings.github_owner or "").strip()
    repo = (settings.github_repo or "").strip()
    token = (settings.github_token or "").strip()
    default_assignee = (settings.github_default_assignee or "").strip() or None

    missing: list[str] = []
    if not owner:
        missing.append("GITHUB_OWNER")
    if not repo:
        missing.append("GITHUB_REPO")
    if not token:
        missing.append("GITHUB_TOKEN")

    if missing:
        missing_csv = ", ".join(missing)
        raise ValueError(
            "GitHub issue creation is not configured. Missing environment "
            f"variables: {missing_csv}"
        )

    return owner, repo, token, default_assignee


def _build_issue_body(payload: dict[str, Any]) -> str:
    """Build a deterministic issue body from a normalized request payload."""
    discovered_traits = payload["discovered_traits"]
    missing_tools = payload["missing_tools"]
    details = payload["details"]

    traits_line = ", ".join(discovered_traits) if discovered_traits else "none"
    tools_line = ", ".join(missing_tools) if missing_tools else "none"
    details_block = details if details else "No additional details provided."

    return (
        "## Kit Extension Request\n\n"
        f"**Summary**\n{payload['summary']}\n\n"
        f"**Discovered Traits**\n{traits_line}\n\n"
        f"**Missing Tools**\n{tools_line}\n\n"
        f"**Details**\n{details_block}"
    )


def _github_api_request(
    *,
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Perform a GitHub API request and parse the JSON response."""
    data = None
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = request.Request(
        url=url,
        data=data,
        method=method,
        headers=headers,
    )

    try:
        with request.urlopen(req, timeout=10) as response:
            response_body = response.read().decode("utf-8")
            return json.loads(response_body)
    except error.HTTPError as exc:
        body_bytes = exc.read()
        body_text = body_bytes.decode("utf-8", errors="replace").strip()
        body_text = body_text or "<empty response body>"
        raise ValueError(
            "GitHub API request failed with status "
            f"{exc.code}: {body_text}"
        ) from exc
    except error.URLError as exc:
        reason = str(exc.reason)
        raise ValueError(
            f"GitHub API request failed due to network error: {reason}"
        ) from exc


def _extract_issue_metadata(
    *,
    owner: str,
    repo: str,
    issue: dict[str, Any],
) -> dict[str, Any]:
    """Project a GitHub issue payload into a compact response structure."""
    return {
        "owner": owner,
        "repo": repo,
        "number": issue.get("number"),
        "url": issue.get("html_url"),
        "title": issue.get("title"),
        "state": issue.get("state"),
    }


def _find_existing_github_issue(
    *,
    owner: str,
    repo: str,
    token: str,
    issue_title: str,
    summary: str,
) -> dict[str, Any] | None:
    """Find an existing open issue that matches this gap request."""
    query = f'repo:{owner}/{repo} is:issue is:open in:title "{issue_title}"'
    params = urlencode({"q": query, "per_page": 10})
    url = f"https://api.github.com/search/issues?{params}"
    payload = _github_api_request(method="GET", url=url, token=token)
    items = payload.get("items")
    if not isinstance(items, list):
        return None

    normalized_title = _normalize_issue_title(issue_title)
    summary_normalized = _normalize_issue_title(summary)
    for item in items:
        if not isinstance(item, dict):
            continue
        if _normalize_issue_title(item.get("title") or "") != normalized_title:
            continue
        body = item.get("body")
        body_text = body if isinstance(body, str) else ""
        if summary_normalized not in _normalize_issue_title(body_text):
            continue
        return item

    return None


def _create_github_issue(
    *,
    owner: str,
    repo: str,
    token: str,
    title: str,
    body: str,
    default_assignee: str | None,
) -> dict[str, Any]:
    """Create a GitHub issue in the configured repository."""
    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    issue_payload: dict[str, Any] = {"title": title, "body": body}
    if default_assignee:
        issue_payload["assignees"] = [default_assignee]

    return _github_api_request(
        method="POST",
        url=url,
        token=token,
        payload=issue_payload,
    )


def check_existing_kit_extension_issue(
    *,
    title: str,
    summary: str,
    discovered_traits: list[str] | None = None,
    missing_tools: list[str] | None = None,
    details: str | None = None,
) -> dict[str, Any]:
    """Check whether a matching open GitHub issue already exists."""
    payload = _normalize_request_payload(
        title=title,
        summary=summary,
        discovered_traits=discovered_traits,
        missing_tools=missing_tools,
        details=details,
    )
    owner, repo, token, _ = _require_github_issue_config()
    issue_title = _build_issue_title(payload["title"])
    existing_issue = _find_existing_github_issue(
        owner=owner,
        repo=repo,
        token=token,
        issue_title=issue_title,
        summary=payload["summary"],
    )

    return {
        "exists": existing_issue is not None,
        "request": payload,
        "github_issue": (
            _extract_issue_metadata(owner=owner, repo=repo, issue=existing_issue)
            if existing_issue is not None
            else None
        ),
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
    Accept extension/clarification requests and create a GitHub issue.

    :raises ValueError: If title or summary is empty.
    """
    payload = _normalize_request_payload(
        title=title,
        summary=summary,
        discovered_traits=discovered_traits,
        missing_tools=missing_tools,
        details=details,
    )

    owner, repo, token, default_assignee = _require_github_issue_config()
    issue_title = _build_issue_title(payload["title"])
    existing_issue = _find_existing_github_issue(
        owner=owner,
        repo=repo,
        token=token,
        issue_title=issue_title,
        summary=payload["summary"],
    )
    if existing_issue is not None:
        return {
            "status": "duplicate",
            "message": "Matching GitHub issue already exists.",
            "request": payload,
            "github_issue": _extract_issue_metadata(
                owner=owner,
                repo=repo,
                issue=existing_issue,
            ),
        }

    issue = _create_github_issue(
        owner=owner,
        repo=repo,
        token=token,
        title=issue_title,
        body=_build_issue_body(payload),
        default_assignee=default_assignee,
    )

    return {
        "status": "created",
        "message": "Request materialized as GitHub issue.",
        "request": payload,
        "github_issue": _extract_issue_metadata(owner=owner, repo=repo, issue=issue),
    }
