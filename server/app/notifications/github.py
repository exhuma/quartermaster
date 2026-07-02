"""GitHub Issues implementation of the ``IssueBackend`` protocol."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.notifications.base import (
    GapReport,
    IssueRef,
    build_issue_body,
    build_issue_title,
    http_request_json,
    normalize_issue_title,
)


class GitHubBackend:
    """Files/dedupes kit-extension requests as GitHub issues."""

    name = "github"

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        token: str,
        default_assignee: str | None = None,
    ) -> None:
        self._owner = owner
        self._repo = repo
        self._token = token
        self._default_assignee = default_assignee

    @classmethod
    def from_settings(cls, settings: Any) -> GitHubBackend:
        """Build a backend from app settings, validating required fields.

        :raises ValueError: If any required ``GITHUB_*`` setting is missing.
        """
        owner = (settings.github_owner or "").strip()
        repo = (settings.github_repo or "").strip()
        token = (settings.github_token or "").strip()
        default_assignee = (
            settings.github_default_assignee or ""
        ).strip() or None

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

        return cls(
            owner=owner,
            repo=repo,
            token=token,
            default_assignee=default_assignee,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def find_existing(self, report: GapReport) -> IssueRef | None:
        issue_title = build_issue_title(report.title)
        query = (
            f"repo:{self._owner}/{self._repo} is:issue is:open "
            f'in:title "{issue_title}"'
        )
        params = urlencode({"q": query, "per_page": 10})
        url = f"https://api.github.com/search/issues?{params}"
        payload = http_request_json(
            method="GET", url=url, headers=self._headers()
        )
        items = payload.get("items")
        if not isinstance(items, list):
            return None

        normalized_title = normalize_issue_title(issue_title)
        summary_normalized = normalize_issue_title(report.summary)
        for item in items:
            if not isinstance(item, dict):
                continue
            item_title = normalize_issue_title(item.get("title") or "")
            if item_title != normalized_title:
                continue
            body = item.get("body")
            body_text = body if isinstance(body, str) else ""
            if summary_normalized not in normalize_issue_title(body_text):
                continue
            return self._to_ref(item)

        return None

    def create(self, report: GapReport) -> IssueRef:
        issue_title = build_issue_title(report.title)
        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/issues"
        payload: dict[str, Any] = {
            "title": issue_title,
            "body": build_issue_body(report),
        }
        if self._default_assignee:
            payload["assignees"] = [self._default_assignee]

        issue = http_request_json(
            method="POST",
            url=url,
            headers=self._headers(),
            json=payload,
        )
        return self._to_ref(issue)

    def _to_ref(self, issue: dict[str, Any]) -> IssueRef:
        return IssueRef(
            backend=self.name,
            project=f"{self._owner}/{self._repo}",
            number=issue.get("number"),
            url=issue.get("html_url"),
            title=issue.get("title"),
            state=issue.get("state"),
        )
