"""Tests for conditional registration of the gap-filing MCP tools."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.main import _build_mcp_instructions, _gap_tools_enabled


def _fake_settings(
    *,
    owner: str | None = "o",
    repo: str | None = "r",
    token: str | None = "t",
    issue_backend: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        issue_backend=issue_backend,
        github_owner=owner,
        github_repo=repo,
        github_token=token,
        github_default_assignee=None,
    )


def test_gap_tools_enabled_when_github_fully_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.get_settings", lambda: _fake_settings())
    assert _gap_tools_enabled() is True


@pytest.mark.parametrize("missing", ["owner", "repo", "token"])
def test_gap_tools_disabled_when_any_github_field_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    settings = _fake_settings(**{missing: None})
    monkeypatch.setattr("app.main.get_settings", lambda: settings)
    assert _gap_tools_enabled() is False


def test_gap_tools_disabled_when_blank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.main.get_settings", lambda: _fake_settings(token="   ")
    )
    assert _gap_tools_enabled() is False


def test_gap_tools_disabled_when_settings_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise() -> SimpleNamespace:
        raise ValidationError.from_exception_data("Settings", [])

    monkeypatch.setattr("app.main.get_settings", _raise)
    assert _gap_tools_enabled() is False


def test_gap_tools_enabled_when_gitlab_selected_and_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: SimpleNamespace(
            issue_backend="gitlab",
            github_owner=None,
            github_repo=None,
            github_token=None,
            github_default_assignee=None,
            gitlab_base_url="https://gitlab.example.com",
            gitlab_project_id="42",
            gitlab_token="glpat-token",
            gitlab_default_assignee_id=None,
        ),
    )
    assert _gap_tools_enabled() is True


def test_gap_tools_disabled_when_backend_explicitly_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.main.get_settings",
        lambda: _fake_settings(issue_backend="none"),
    )
    assert _gap_tools_enabled() is False


def test_instructions_include_gap_tools_when_enabled() -> None:
    text = _build_mcp_instructions(gap_enabled=True)
    assert "check_existing_gap_issue" in text
    assert "request_clarification_or_addition" in text
    assert "Hard-coding kits" in text


def test_instructions_omit_gap_tools_when_disabled() -> None:
    text = _build_mcp_instructions(gap_enabled=False)
    assert "check_existing_gap_issue" not in text
    assert "request_clarification_or_addition" not in text
    # The (backend-independent) closing guidance still survives.
    assert "Hard-coding kits" in text


def test_instructions_keep_core_loop_in_both_modes() -> None:
    for enabled in (True, False):
        text = _build_mcp_instructions(gap_enabled=enabled)
        for tool in ("list_available_traits", "select_kits", "get_kit"):
            assert tool in text
        assert "per task" in text.lower()
