"""Tests for canned prompt definitions."""

from __future__ import annotations

import pytest

from app.prompts import get_canned_prompt, list_canned_prompts
from app.templating import render_asset


def test_list_canned_prompts_has_expected_entries() -> None:
    prompts = list_canned_prompts()
    names = {prompt["name"] for prompt in prompts}
    assert names == {
        "greet",
        "integrate_project",
        "trait_selection_bootstrap",
        "legacy_assessment",
        "bootstrap_sequence",
        "capability_extension",
        "tech_debt_modernization",
        "bootstrap_project_skills",
        "audit_project_skills",
        "maintain_project_skills",
    }


def test_prompt_bodies_load_from_bundled_markdown() -> None:
    """Every prompt's body is sourced (non-empty) from its bundled markdown."""
    for prompt in list_canned_prompts():
        assert prompt["prompt_template"].strip()


def test_render_asset_loads_bundled_prompt() -> None:
    """The templating loader resolves a bundled prompt asset by path."""
    body = render_asset("prompts", "audit-project-skills.md")
    assert "Audit Project Skills" in body


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


def test_bootstrap_prompt_leads_with_resolve_kits() -> None:
    """The bootstrap routine recommends the one-shot tool before the loop."""
    template = get_canned_prompt("trait_selection_bootstrap")["prompt_template"]
    assert "resolve_kits" in template
    # Introduced ahead of the manual select_kits step.
    assert template.index("resolve_kits") < template.index("select_kits")


def test_get_canned_prompt_returns_prompt() -> None:
    prompt = get_canned_prompt("legacy_assessment")
    assert prompt["title"] == "Legacy Project Diagnostic"
    assert "prompt_template" in prompt


def test_get_canned_prompt_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        get_canned_prompt("missing")
