"""Tests for canned prompt definitions."""

from __future__ import annotations

import pytest

from app.prompts import get_canned_prompt, list_canned_prompts


def test_list_canned_prompts_has_expected_entries() -> None:
    prompts = list_canned_prompts()
    names = {prompt["name"] for prompt in prompts}
    assert names == {
        "trait_selection_bootstrap",
        "legacy_assessment",
        "bootstrap_sequence",
        "capability_extension",
        "tech_debt_modernization",
    }


def test_trait_selection_bootstrap_prompt_is_quartermaster_usage() -> None:
    """The bootstrap prompt teaches *using* Quartermaster, not project work.

    It must make the supported trait categories authoritative, cover
    normalization of free-form wording, and recommend broadening before giving
    up — the failure mode it exists to prevent.
    """
    prompt = get_canned_prompt("trait_selection_bootstrap")
    intent = prompt["intent"].lower()
    template = prompt["prompt_template"].lower()
    # Obviously about driving Quartermaster, not implementing the target repo.
    assert "quartermaster" in intent
    assert "not" in intent  # disclaims project-implementation use
    # The four authoritative trait categories.
    for category in ("languages", "frameworks", "capabilities", "contexts"):
        assert category in template
    assert "normalize" in template
    assert "broaden" in template


def test_get_canned_prompt_returns_prompt() -> None:
    prompt = get_canned_prompt("legacy_assessment")
    assert prompt["title"] == "Legacy Project Diagnostic"
    assert "prompt_template" in prompt


def test_get_canned_prompt_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_canned_prompt("missing")
