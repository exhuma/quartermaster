"""Tests for the pluggable IssueBackend abstraction (GitHub backend)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.notifications import (
    check_existing_kit_extension_issue,
    gap_tools_enabled,
    get_issue_backend,
    request_kit_extension,
)
from app.notifications.github import GitHubBackend
from app.notifications.gitlab import GitLabBackend


def _set_github_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner: str | None = "test-owner",
    repo: str | None = "test-repo",
    token: str | None = "test-token",
    assignee: str | None = None,
) -> None:
    monkeypatch.setattr(
        "app.notifications.get_settings",
        lambda: SimpleNamespace(
            issue_backend=None,
            github_owner=owner,
            github_repo=repo,
            github_token=token,
            github_default_assignee=assignee,
        ),
    )


def test_request_kit_extension_creates_github_issue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch, assignee="octocat")
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        GitHubBackend, "find_existing", lambda self, report: None
    )

    def fake_create(self: GitHubBackend, report):
        captured["owner"] = self._owner
        captured["repo"] = self._repo
        captured["token"] = self._token
        captured["default_assignee"] = self._default_assignee
        captured["title"] = report.title
        from app.notifications.base import IssueRef

        return IssueRef(
            backend="github",
            project=f"{self._owner}/{self._repo}",
            number=42,
            url="https://github.com/test-owner/test-repo/issues/42",
            title=f"[Kit Request] {report.title}",
            state="open",
        )

    monkeypatch.setattr(GitHubBackend, "create", fake_create)

    result = request_kit_extension(
        title="Need new auth trait",
        summary="Project uses a trait not covered by current manifests",
        discovered_traits=["Auth0", "AUTH0", ""],
        missing_tools=["suggest_new_module", "suggest_new_module"],
        details="Please add OIDC-provider trait guidance.",
    )

    assert result["status"] == "created"
    assert result["request"]["discovered_traits"] == ["auth0"]
    assert result["request"]["missing_tools"] == ["suggest_new_module"]
    assert result["request"]["details"] == (
        "Please add OIDC-provider trait guidance."
    )
    assert result["issue"]["number"] == 42
    assert (
        result["issue"]["url"]
        == "https://github.com/test-owner/test-repo/issues/42"
    )

    assert captured["owner"] == "test-owner"
    assert captured["repo"] == "test-repo"
    assert captured["token"] == "test-token"
    assert captured["default_assignee"] == "octocat"
    assert captured["title"] == "Need new auth trait"


def test_request_kit_extension_requires_github_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch, owner=None, repo="test-repo", token=None)

    with pytest.raises(ValueError, match="Missing environment variables"):
        request_kit_extension(title="valid", summary="valid")


def test_request_kit_extension_surfaces_issue_creation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)
    monkeypatch.setattr(
        GitHubBackend, "find_existing", lambda self, report: None
    )

    def fake_create(self: GitHubBackend, report):
        raise ValueError("GitHub API request failed with status 401: denied")

    monkeypatch.setattr(GitHubBackend, "create", fake_create)

    with pytest.raises(ValueError, match="status 401"):
        request_kit_extension(title="valid", summary="valid")


def test_request_kit_extension_returns_duplicate_when_issue_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)

    from app.notifications.base import IssueRef

    monkeypatch.setattr(
        GitHubBackend,
        "find_existing",
        lambda self, report: IssueRef(
            backend="github",
            project="test-owner/test-repo",
            number=7,
            url="https://github.com/test-owner/test-repo/issues/7",
            title="[Kit Request] valid",
            state="open",
        ),
    )

    def fail_create(self: GitHubBackend, report):
        raise AssertionError("create should not be called")

    monkeypatch.setattr(GitHubBackend, "create", fail_create)

    result = request_kit_extension(title="valid", summary="valid")
    assert result["status"] == "duplicate"
    assert result["issue"]["number"] == 7


def test_check_existing_kit_extension_issue_reports_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)

    from app.notifications.base import IssueRef

    monkeypatch.setattr(
        GitHubBackend,
        "find_existing",
        lambda self, report: IssueRef(
            backend="github",
            project="test-owner/test-repo",
            number=11,
            url="https://github.com/test-owner/test-repo/issues/11",
            title="[Kit Request] Need new auth trait",
            state="open",
        ),
    )

    result = check_existing_kit_extension_issue(
        title="Need new auth trait",
        summary="Project uses a trait not covered by current manifests",
    )
    assert result["exists"] is True
    assert result["issue"]["number"] == 11


def test_check_existing_kit_extension_issue_reports_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)
    monkeypatch.setattr(
        GitHubBackend, "find_existing", lambda self, report: None
    )

    result = check_existing_kit_extension_issue(title="valid", summary="valid")
    assert result["exists"] is False
    assert result["issue"] is None


def test_request_kit_extension_requires_non_empty_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)

    with pytest.raises(ValueError):
        request_kit_extension(title="   ", summary="valid")


def test_request_kit_extension_requires_non_empty_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)

    with pytest.raises(ValueError):
        request_kit_extension(title="valid", summary="   ")


def test_github_backend_find_existing_matches_normalized_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Title differs only by case and inner/trailing whitespace; body
    # contains the summary with differing spacing.
    monkeypatch.setattr(
        "app.notifications.github.http_request_json",
        lambda **_: {
            "items": [
                {
                    "title": "[Kit Request]  Need  New  Auth Trait ",
                    "body": "Project uses a   trait not covered",
                    "number": 5,
                    "html_url": "https://example/5",
                }
            ]
        },
    )
    backend = GitHubBackend(
        owner="test-owner", repo="test-repo", token="t", default_assignee=None
    )
    from app.notifications.base import GapReport

    match = backend.find_existing(
        GapReport(
            title="Need New Auth Trait",
            summary="Project uses a trait not covered",
        )
    )
    assert match is not None
    assert match.number == 5


def test_github_backend_find_existing_no_match_on_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.notifications.github.http_request_json",
        lambda **_: {
            "items": [
                {
                    "title": "[Kit Request] Totally Different Thing",
                    "body": "unrelated body",
                    "number": 9,
                }
            ]
        },
    )
    backend = GitHubBackend(
        owner="test-owner", repo="test-repo", token="t", default_assignee=None
    )
    from app.notifications.base import GapReport

    match = backend.find_existing(
        GapReport(
            title="Need New Auth Trait",
            summary="Project uses a trait not covered",
        )
    )
    assert match is None


def _gitlab_settings(
    *,
    issue_backend: str | None = "gitlab",
    base_url: str = "https://gitlab.example.com",
    project_id: str | None = "42",
    token: str | None = "glpat-token",
    assignee_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        issue_backend=issue_backend,
        github_owner=None,
        github_repo=None,
        github_token=None,
        github_default_assignee=None,
        gitlab_base_url=base_url,
        gitlab_project_id=project_id,
        gitlab_token=token,
        gitlab_default_assignee_id=assignee_id,
    )


def test_gitlab_backend_find_existing_matches_normalized_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_http(*, method, url, headers, **_):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return [
            {
                "title": "[Kit Request]  Need  New  Auth Trait ",
                "description": "Project uses a   trait not covered",
                "iid": 5,
                "web_url": "https://gitlab.example.com/g/p/-/issues/5",
                "state": "opened",
            }
        ]

    monkeypatch.setattr("app.notifications.gitlab.http_request_json", fake_http)

    from app.notifications.base import GapReport

    backend = GitLabBackend(
        base_url="https://gitlab.example.com",
        project_id="42",
        token="glpat-token",
        default_assignee_id=None,
    )
    match = backend.find_existing(
        GapReport(
            title="Need New Auth Trait",
            summary="Project uses a trait not covered",
        )
    )
    assert match is not None
    assert match.number == 5
    assert match.url == "https://gitlab.example.com/g/p/-/issues/5"
    assert captured["headers"]["PRIVATE-TOKEN"] == "glpat-token"
    assert "state=opened" in captured["url"]
    assert "in=title" in captured["url"]
    assert "/api/v4/projects/42/issues" in captured["url"]


def test_gitlab_backend_find_existing_no_match_on_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.notifications.gitlab.http_request_json",
        lambda **_: [
            {
                "title": "[Kit Request] Totally Different Thing",
                "description": "unrelated body",
                "iid": 9,
            }
        ],
    )

    from app.notifications.base import GapReport

    backend = GitLabBackend(
        base_url="https://gitlab.example.com",
        project_id="42",
        token="glpat-token",
        default_assignee_id=None,
    )
    match = backend.find_existing(
        GapReport(
            title="Need New Auth Trait",
            summary="Project uses a trait not covered",
        )
    )
    assert match is None


def test_gitlab_backend_create_maps_iid_and_web_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_http(*, method, url, headers, json=None, **_):
        captured["method"] = method
        captured["url"] = url
        captured["json"] = json
        return {
            "iid": 17,
            "web_url": "https://gitlab.example.com/g/p/-/issues/17",
            "title": "[Kit Request] Need new auth trait",
            "state": "opened",
        }

    monkeypatch.setattr("app.notifications.gitlab.http_request_json", fake_http)

    from app.notifications.base import GapReport

    backend = GitLabBackend(
        base_url="https://gitlab.example.com",
        project_id="42",
        token="glpat-token",
        default_assignee_id=99,
    )
    ref = backend.create(
        GapReport(title="Need new auth trait", summary="Project needs OIDC")
    )
    assert ref.number == 17
    assert ref.url == "https://gitlab.example.com/g/p/-/issues/17"
    assert captured["method"] == "POST"
    assert captured["json"]["assignee_ids"] == [99]
    assert captured["json"]["title"] == "[Kit Request] Need new auth trait"


def test_gitlab_backend_from_settings_requires_project_and_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Missing environment variables"):
        GitLabBackend.from_settings(
            _gitlab_settings(project_id=None, token=None)
        )


def test_get_issue_backend_returns_none_when_unconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.notifications.get_settings",
        lambda: SimpleNamespace(
            issue_backend="none",
            github_owner=None,
            github_repo=None,
            github_token=None,
            github_default_assignee=None,
        ),
    )
    assert get_issue_backend() is None
    assert gap_tools_enabled() is False


def test_get_issue_backend_defaults_to_github_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)
    backend = get_issue_backend()
    assert isinstance(backend, GitHubBackend)
    assert gap_tools_enabled() is True


def test_get_issue_backend_selects_gitlab_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.notifications.get_settings", lambda: _gitlab_settings()
    )
    backend = get_issue_backend()
    assert isinstance(backend, GitLabBackend)
    assert gap_tools_enabled() is True


def test_get_issue_backend_none_when_selected_backend_underconfigured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.notifications.get_settings",
        lambda: _gitlab_settings(project_id=None, token=None),
    )
    assert get_issue_backend() is None
    assert gap_tools_enabled() is False


def test_request_kit_extension_uses_gitlab_backend_when_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.notifications.get_settings", lambda: _gitlab_settings()
    )
    monkeypatch.setattr(
        GitLabBackend, "find_existing", lambda self, report: None
    )

    from app.notifications.base import IssueRef

    def fake_create(self: GitLabBackend, report):
        return IssueRef(
            backend="gitlab",
            project="42",
            number=3,
            url="https://gitlab.example.com/g/p/-/issues/3",
            title=f"[Kit Request] {report.title}",
            state="opened",
        )

    monkeypatch.setattr(GitLabBackend, "create", fake_create)

    result = request_kit_extension(title="Need OIDC", summary="Please add OIDC")
    assert result["status"] == "created"
    assert result["issue"]["number"] == 3


def test_get_issue_backend_tolerates_settings_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Safe to call at import/module-load time (or mid-resolve) even when
    # required Keycloak settings are absent, mirroring every other
    # "am I configured" gate in this codebase.
    from pydantic import ValidationError

    def _raise() -> SimpleNamespace:
        raise ValidationError.from_exception_data("Settings", [])

    monkeypatch.setattr("app.notifications.get_settings", _raise)
    assert get_issue_backend() is None
    assert gap_tools_enabled() is False
