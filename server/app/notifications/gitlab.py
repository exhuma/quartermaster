"""GitLab Issues implementation of the ``IssueBackend`` protocol."""

from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlencode

from app.notifications.base import (
    GapReport,
    IssueRef,
    build_issue_body,
    build_issue_title,
    http_request_json,
    normalize_issue_title,
)


class GitLabBackend:
    """Files/dedupes kit-extension requests as GitLab issues (API v4)."""

    name = "gitlab"

    def __init__(
        self,
        *,
        base_url: str,
        project_id: str,
        token: str,
        default_assignee_id: int | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._project_id = project_id
        self._token = token
        self._default_assignee_id = default_assignee_id

    @classmethod
    def from_settings(cls, settings: Any) -> GitLabBackend:
        """Build a backend from app settings, validating required fields.

        :raises ValueError: If any required ``GITLAB_*`` setting is missing.
        """
        base_url = (settings.gitlab_base_url or "https://gitlab.com").strip()
        project_id = (settings.gitlab_project_id or "").strip()
        token = (settings.gitlab_token or "").strip()
        default_assignee_id = getattr(
            settings, "gitlab_default_assignee_id", None
        )

        missing: list[str] = []
        if not project_id:
            missing.append("GITLAB_PROJECT_ID")
        if not token:
            missing.append("GITLAB_TOKEN")

        if missing:
            missing_csv = ", ".join(missing)
            raise ValueError(
                "GitLab issue creation is not configured. Missing environment "
                f"variables: {missing_csv}"
            )

        return cls(
            base_url=base_url,
            project_id=project_id,
            token=token,
            default_assignee_id=default_assignee_id,
        )

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self._token}

    def _issues_url(self) -> str:
        project_path = quote(str(self._project_id), safe="")
        return f"{self._base_url}/api/v4/projects/{project_path}/issues"

    def find_existing(self, report: GapReport) -> IssueRef | None:
        issue_title = build_issue_title(report.title)
        params = urlencode(
            {
                "state": "opened",
                "search": issue_title,
                "in": "title",
                "per_page": 20,
            }
        )
        url = f"{self._issues_url()}?{params}"
        payload = http_request_json(
            method="GET", url=url, headers=self._headers()
        )
        if not isinstance(payload, list):
            return None

        normalized_title = normalize_issue_title(issue_title)
        summary_normalized = normalize_issue_title(report.summary)
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_title = normalize_issue_title(item.get("title") or "")
            if item_title != normalized_title:
                continue
            body = item.get("description")
            body_text = body if isinstance(body, str) else ""
            if summary_normalized not in normalize_issue_title(body_text):
                continue
            return self._to_ref(item)

        return None

    def create(self, report: GapReport) -> IssueRef:
        issue_title = build_issue_title(report.title)
        payload: dict[str, Any] = {
            "title": issue_title,
            "description": build_issue_body(report),
        }
        if self._default_assignee_id:
            payload["assignee_ids"] = [self._default_assignee_id]

        issue = http_request_json(
            method="POST",
            url=self._issues_url(),
            headers=self._headers(),
            json=payload,
        )
        return self._to_ref(issue)

    def _to_ref(self, issue: dict[str, Any]) -> IssueRef:
        return IssueRef(
            backend=self.name,
            project=str(self._project_id),
            number=issue.get("iid"),
            url=issue.get("web_url"),
            title=issue.get("title"),
            state=issue.get("state"),
        )
