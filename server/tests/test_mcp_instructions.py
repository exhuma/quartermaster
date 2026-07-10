"""Tests for the server-level MCP usage instructions."""

from __future__ import annotations

from app.main import MCP_INSTRUCTIONS, mcp


def test_server_ships_instructions() -> None:
    assert mcp.instructions == MCP_INSTRUCTIONS
    assert MCP_INSTRUCTIONS.strip()


def test_instructions_describe_per_task_reflection() -> None:
    text = MCP_INSTRUCTIONS.lower()
    # The intended workflow: per-task trait reflection, not a hard-coded list.
    assert "per task" in text
    assert "claude.md" in text  # discourages hard-coding a fixed kit list
    # The three discovery/loading tools that make up the loop.
    for tool in ("list_available_traits", "select_kits", "get_kit"):
        assert tool in MCP_INSTRUCTIONS


def test_instructions_lead_with_one_shot_tool() -> None:
    """`resolve_kits` is presented as the default, ahead of the manual loop.

    Agents follow the first concrete instruction they are given; if the manual
    loop comes first they never reach the one-shot tool (the real failure mode
    we observed). The default path must be introduced before the fallback.
    """
    text = MCP_INSTRUCTIONS
    assert "resolve_kits" in text
    # The one-shot tool is introduced before the manual discovery tools.
    assert text.index("resolve_kits") < text.index("list_available_traits")
    assert text.index("resolve_kits") < text.index("select_kits")


def test_instructions_carry_normalization_invariant() -> None:
    """The description holds the tiny trait-normalization invariant.

    This is what steers an agent away from generic/invented traits and toward
    the server's authoritative vocabulary, broadening before giving up.
    """
    text = " ".join(MCP_INSTRUCTIONS.lower().split())
    assert "authoritative" in text
    assert "normalize" in text
    assert "adjacent supported traits" in text


def test_instructions_point_to_bootstrap_prompt_registry() -> None:
    """The description points at the prompt registry for the full routine.

    It references the discovery tools generically rather than hard-coding a
    single fixed prompt name, so the bootstrap artifact can evolve.
    """
    assert "list_prompts" in MCP_INSTRUCTIONS
    assert "get_prompt" in MCP_INSTRUCTIONS


def test_instructions_cover_version_pinning() -> None:
    """The description tells agents how to remember a kit's pinned major."""
    text = MCP_INSTRUCTIONS
    assert ".quartermaster.toml" in text
    assert "version_advisory" in text
    assert "pin" in text.lower()
    # Points at the canonical pin-file prompt for the full workflow.
    assert "quartermaster_pin_file" in text
