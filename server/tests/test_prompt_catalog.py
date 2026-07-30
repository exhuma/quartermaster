"""
Tests for ``app.prompt_catalog``: layering, private-overlay shadowing,
broken/malformed-content resilience, and frontmatter parsing edge cases.

Mirrors ``tests/test_private_kit_isolation.py``'s style but for the
sectionless, version-less prompts catalog.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app import prompt_catalog as pc
from app.config import KitLayerConfig
from app.identity import reset_identity, set_identity
from app.private_prompts import private_root_for


def _write_prompt(
    root: Path,
    name: str,
    *,
    title: str = "",
    description: str = "",
    body: str = "Body text.",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    content = pc.render_prompt_file(title, description, body)
    (root / f"{name}.md").write_text(content, encoding="utf-8")


@pytest.fixture()
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A shared prompts layer with one prompt, plus a private root config."""
    shared = tmp_path / "prompts"
    private = tmp_path / "private-prompts"
    shared.mkdir()
    layers = [KitLayerConfig(name="default", path=shared, readonly=False)]
    settings = SimpleNamespace(
        effective_prompt_layers=layers, private_prompts_root=private
    )
    monkeypatch.setattr(pc, "get_settings", lambda: settings)
    monkeypatch.setattr("app.private_prompts.get_settings", lambda: settings)
    _write_prompt(
        shared,
        "shared-prompt",
        title="Shared",
        description="A shared prompt.",
        body="Shared body.",
    )
    return SimpleNamespace(shared=shared, private=private)


def _names(prompts) -> set[str]:
    return {p.name for p in prompts}


# ---------------------------------------------------------------------------
# Layering / private overlay
# ---------------------------------------------------------------------------


def test_list_all_prompts_returns_shared(catalog) -> None:
    assert _names(pc.list_all_prompts(subject=None)) == {"shared-prompt"}


def test_owner_sees_private_prompt(catalog) -> None:
    _write_prompt(private_root_for("alice-sub"), "alice-notes", body="Notes.")
    assert _names(pc.list_all_prompts(subject="alice-sub")) == {
        "shared-prompt",
        "alice-notes",
    }


def test_other_user_cannot_see_private_prompt(catalog) -> None:
    _write_prompt(private_root_for("alice-sub"), "alice-notes", body="Notes.")
    assert _names(pc.list_all_prompts(subject="bob-sub")) == {"shared-prompt"}
    assert _names(pc.list_all_prompts(subject=None)) == {"shared-prompt"}


def test_list_private_prompts_helper(catalog) -> None:
    _write_prompt(private_root_for("alice-sub"), "alice-notes", body="Notes.")
    assert _names(pc.list_private_prompts("alice-sub")) == {"alice-notes"}
    assert pc.list_private_prompts("bob-sub") == []
    assert pc.list_private_prompts("") == []


def test_private_shadows_shared_for_owner_only(catalog) -> None:
    _write_prompt(
        private_root_for("alice-sub"),
        "shared-prompt",
        body="Alice's private version.",
    )
    mine = pc.read_prompt("shared-prompt", subject="alice-sub")
    assert mine.body == "Alice's private version."
    assert mine.source_layer == pc._PRIVATE_LAYER_NAME

    others = pc.read_prompt("shared-prompt", subject="bob-sub")
    assert others.body == "Shared body."
    public = pc.read_prompt("shared-prompt", subject=None)
    assert public.body == "Shared body."


def test_read_missing_prompt_raises_not_found(catalog) -> None:
    with pytest.raises(pc.PromptNotFoundError):
        pc.read_prompt("nope", subject=None)


def test_contextvar_default_subject_is_owner_aware(catalog) -> None:
    """MCP tools rely on the contextvar: no subject arg → owner-aware."""
    assert _names(pc.list_all_prompts()) == {"shared-prompt"}
    tokens = set_identity("alice-sub", "Alice")
    try:
        _write_prompt(private_root_for("alice-sub"), "alice-notes", body="x")
        assert "alice-notes" in _names(pc.list_all_prompts())
    finally:
        reset_identity(tokens)
    assert _names(pc.list_all_prompts()) == {"shared-prompt"}


# ---------------------------------------------------------------------------
# Broken / malformed content resilience
# ---------------------------------------------------------------------------


def test_list_all_prompts_marks_broken_entry(catalog) -> None:
    (catalog.shared / "broken-prompt.md").write_text(
        "---\nauthor: nope\n---\nBody\n", encoding="utf-8"
    )
    entries = {p.name: p for p in pc.list_all_prompts(subject=None)}
    assert entries["broken-prompt"].broken is True
    assert entries["broken-prompt"].error
    assert entries["shared-prompt"].broken is False


def test_read_broken_prompt_raises(catalog) -> None:
    (catalog.shared / "broken-prompt.md").write_text(
        "---\nunclosed\nBody\n", encoding="utf-8"
    )
    with pytest.raises(pc.PromptValidationError):
        pc.read_prompt("broken-prompt", subject=None)


# ---------------------------------------------------------------------------
# Frontmatter parsing
# ---------------------------------------------------------------------------


def test_missing_frontmatter_is_valid_body_only() -> None:
    meta, body = pc._parse_frontmatter("Just a body.\nSecond line.\n")
    assert meta == {}
    assert body == "Just a body.\nSecond line.\n"


def test_unknown_frontmatter_key_rejected() -> None:
    with pytest.raises(pc.PromptValidationError):
        pc._parse_frontmatter("---\nauthor: bob\n---\nBody\n")


def test_frontmatter_line_without_colon_rejected() -> None:
    with pytest.raises(pc.PromptValidationError):
        pc._parse_frontmatter("---\njust some text\n---\nBody\n")


def test_unclosed_frontmatter_block_rejected() -> None:
    with pytest.raises(pc.PromptValidationError):
        pc._parse_frontmatter("---\ntitle: X\nBody without closing\n")


def test_render_and_parse_round_trip() -> None:
    rendered = pc.render_prompt_file(
        "My Title", "My description", "Body text.\nMore."
    )
    meta, body = pc._parse_frontmatter(rendered)
    assert meta == {"title": "My Title", "description": "My description"}
    assert body == "Body text.\nMore."


def test_render_omits_frontmatter_when_both_empty() -> None:
    rendered = pc.render_prompt_file("", "", "Just body.")
    assert rendered == "Just body."
    meta, body = pc._parse_frontmatter(rendered)
    assert meta == {}
    assert body == "Just body."


def test_frontmatter_value_may_contain_colon() -> None:
    rendered = pc.render_prompt_file("Title: with colon", "", "Body.")
    meta, body = pc._parse_frontmatter(rendered)
    assert meta["title"] == "Title: with colon"
    assert body == "Body."
