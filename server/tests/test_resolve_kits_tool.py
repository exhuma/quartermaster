"""Tests for the ``resolve_kits`` MCP tool wrapper and its instructions."""

from __future__ import annotations

import asyncio

from app.main import MCP_INSTRUCTIONS, mcp


def _get_tool(name: str):
    return asyncio.run(mcp.get_tool(name))


def test_resolve_kits_tool_is_registered() -> None:
    tool = _get_tool("resolve_kits")
    assert tool is not None
    assert tool.fn is not None


def test_resolve_kits_wrapper_delegates(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    sentinel = {"engine": "lexical", "kits": []}
    captured: dict = {}

    def _fake_resolve(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("app.main._resolve_kits", _fake_resolve)
    result = tool.fn(task="add a FastAPI endpoint", limit=3)
    assert result is sentinel
    assert captured["task"] == "add a FastAPI endpoint"
    assert captured["limit"] == 3


def test_resolve_kits_wrapper_maps_value_error(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")

    def _raise(**kwargs):
        raise ValueError("task must not be empty")

    monkeypatch.setattr("app.main._resolve_kits", _raise)
    try:
        tool.fn(task="")
    except ValueError as exc:
        assert "task" in str(exc)
    else:  # pragma: no cover - explicit failure path
        raise AssertionError("expected ValueError")


def test_instructions_point_at_one_shot_tool() -> None:
    assert "resolve_kits" in MCP_INSTRUCTIONS
