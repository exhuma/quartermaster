"""Tests for clarification/addition request GitHub materialization."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.requests import (
    _find_existing_github_issue,
    check_existing_kit_extension_issue,
    request_kit_extension,
)


def _set_github_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner: str | None = "test-owner",
    repo: str | None = "test-repo",
    token: str | None = "test-token",
    assignee: str | None = None,
) -> None:
    monkeypatch.setattr(
        "app.requests.get_settings",
        lambda: SimpleNamespace(
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
        "app.requests._find_existing_github_issue",
        lambda **_: None,
    )

    def fake_create_issue(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "number": 42,
            "html_url": "https://github.com/test-owner/test-repo/issues/42",
        }

    monkeypatch.setattr("app.requests._create_github_issue", fake_create_issue)

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
    assert result["request"]["details"] == "Please add OIDC-provider trait guidance."
    assert result["github_issue"]["number"] == 42
    assert (
        result["github_issue"]["url"]
        == "https://github.com/test-owner/test-repo/issues/42"
    )

    assert captured["owner"] == "test-owner"
    assert captured["repo"] == "test-repo"
    assert captured["token"] == "test-token"
    assert captured["default_assignee"] == "octocat"
    assert captured["title"] == "[Kit Request] Need new auth trait"
    assert isinstance(captured["body"], str)


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
        "app.requests._find_existing_github_issue",
        lambda **_: None,
    )

    def fake_create_issue(**_: object) -> dict[str, object]:
        raise ValueError("GitHub issue creation failed with status 401: denied")

    monkeypatch.setattr("app.requests._create_github_issue", fake_create_issue)

    with pytest.raises(ValueError, match="status 401"):
        request_kit_extension(title="valid", summary="valid")


def test_request_kit_extension_returns_duplicate_when_issue_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)
    monkeypatch.setattr(
        "app.requests._find_existing_github_issue",
        lambda **_: {
            "number": 7,
            "html_url": "https://github.com/test-owner/test-repo/issues/7",
            "title": "[Kit Request] valid",
            "state": "open",
        },
    )

    def fail_create_issue(**_: object) -> dict[str, object]:
        raise AssertionError("_create_github_issue should not be called")

    monkeypatch.setattr("app.requests._create_github_issue", fail_create_issue)

    result = request_kit_extension(title="valid", summary="valid")
    assert result["status"] == "duplicate"
    assert result["github_issue"]["number"] == 7


def test_check_existing_kit_extension_issue_reports_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)
    monkeypatch.setattr(
        "app.requests._find_existing_github_issue",
        lambda **_: {
            "number": 11,
            "html_url": "https://github.com/test-owner/test-repo/issues/11",
            "title": "[Kit Request] Need new auth trait",
            "state": "open",
        },
    )

    result = check_existing_kit_extension_issue(
        title="Need new auth trait",
        summary="Project uses a trait not covered by current manifests",
    )
    assert result["exists"] is True
    assert result["github_issue"]["number"] == 11


def test_check_existing_kit_extension_issue_reports_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_github_settings(monkeypatch)
    monkeypatch.setattr(
        "app.requests._find_existing_github_issue",
        lambda **_: None,
    )

    result = check_existing_kit_extension_issue(title="valid", summary="valid")
    assert result["exists"] is False
    assert result["github_issue"] is None


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


def test_find_existing_github_issue_matches_normalized_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Title differs only by case and inner/trailing whitespace; body
    # contains the summary with differing spacing.
    monkeypatch.setattr(
        "app.requests._github_api_request",
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
    match = _find_existing_github_issue(
        owner="test-owner",
        repo="test-repo",
        token="t",
        issue_title="[Kit Request] Need New Auth Trait",
        summary="Project uses a trait not covered",
    )
    assert match is not None
    assert match["number"] == 5


def test_find_existing_github_issue_no_match_on_unrelated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.requests._github_api_request",
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
    match = _find_existing_github_issue(
        owner="test-owner",
        repo="test-repo",
        token="t",
        issue_title="[Kit Request] Need New Auth Trait",
        summary="Project uses a trait not covered",
    )
    assert match is None
