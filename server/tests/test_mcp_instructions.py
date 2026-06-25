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
