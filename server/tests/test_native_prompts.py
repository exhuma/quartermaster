"""Tests for the native FastMCP ``@mcp.prompt`` registrations.

The 5 canned templates in :mod:`app.prompts` are exposed both as native MCP
prompts (human-selectable slash commands) and via the existing
``list_prompts``/``get_prompt`` tools (autonomous-agent access). These tests
cover the native-prompt surface and confirm the tools still exist.
"""

from __future__ import annotations

import asyncio

from app.main import mcp
from app.prompts import list_canned_prompts

_EXPECTED = {
    "trait_selection_bootstrap",
    "legacy_assessment",
    "bootstrap_sequence",
    "capability_extension",
    "tech_debt_modernization",
}


def _prompt_names() -> set[str]:
    prompts = asyncio.run(mcp.list_prompts())
    return {p.name for p in prompts}


def test_all_canned_prompts_registered_as_native_prompts() -> None:
    assert _EXPECTED <= _prompt_names()


def test_native_prompt_carries_title_and_description() -> None:
    prompt = asyncio.run(mcp.get_prompt("trait_selection_bootstrap"))
    assert prompt is not None
    canned = next(
        p
        for p in list_canned_prompts()
        if p["name"] == "trait_selection_bootstrap"
    )
    assert prompt.title == canned["title"]
    assert prompt.description == canned["intent"]


def test_native_prompt_renders_template_text() -> None:
    prompt = asyncio.run(mcp.get_prompt("trait_selection_bootstrap"))
    rendered = asyncio.run(prompt.render({}))
    text = "".join(
        msg.content.text
        for msg in rendered.messages
        if hasattr(msg.content, "text")
    )
    # The rendered prompt is the canned template verbatim.
    assert "resolve_kits" in text
    assert "select_kits" in text


def test_prompt_tools_still_registered() -> None:
    # Dual access: the tools must remain for autonomous agents.
    list_tool = asyncio.run(mcp.get_tool("list_prompts"))
    get_tool = asyncio.run(mcp.get_tool("get_prompt"))
    assert list_tool is not None
    assert get_tool is not None
