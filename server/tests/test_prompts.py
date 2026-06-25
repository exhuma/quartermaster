"""Tests for canned prompt definitions."""

from __future__ import annotations

import pytest

from app.prompts import get_canned_prompt, list_canned_prompts


def test_list_canned_prompts_has_expected_entries() -> None:
    prompts = list_canned_prompts()
    names = {prompt["name"] for prompt in prompts}
    assert names == {
        "legacy_assessment",
        "bootstrap_sequence",
        "capability_extension",
        "tech_debt_modernization",
    }


def test_get_canned_prompt_returns_prompt() -> None:
    prompt = get_canned_prompt("legacy_assessment")
    assert prompt["title"] == "Legacy Project Diagnostic"
    assert "prompt_template" in prompt


def test_get_canned_prompt_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_canned_prompt("missing")
