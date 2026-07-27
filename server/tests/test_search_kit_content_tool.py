"""Tests for the ``search_kit_content`` MCP tool wrapper."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from app.main import mcp


def _get_tool(name: str):
    return asyncio.run(mcp.get_tool(name))


def _write_kit(base: Path, name: str, summary: str) -> None:
    instr = base / name / "v1" / "instructions"
    instr.mkdir(parents=True)
    (instr / "overview.md").write_text(
        f"# Agent instructions: {name}\n", encoding="utf-8"
    )
    (instr / "index.toml").write_text(
        f'summary = "{summary}"\n\n'
        '[[sections]]\n'
        'file = "overview.md"\n'
        'title = "Overview"\n'
        'gloss = "What this kit is"\n'
        'always_load = false\n',
        encoding="utf-8",
    )
    (base / name / "applicability.json").write_text(
        json.dumps({
            "kit_type": "module",
            "summary": summary,
            "domains": [],
            "languages": [],
            "frameworks": [],
            "contexts": [],
            "requires": {
                "languages": [], "frameworks": [], "capabilities": [],
                "contexts": [],
            },
            "excludes": {
                "languages": [], "frameworks": [], "capabilities": [],
                "contexts": [],
            },
            "optional_signals": [],
            "related_kits": [],
            "priority": 50,
        }),
        encoding="utf-8",
    )


def test_search_kit_content_tool_is_registered() -> None:
    tool = _get_tool("search_kit_content")
    assert tool is not None
    assert tool.fn is not None


def test_search_kit_content_returns_matching_kit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_kit(tmp_path, "kit-gamma", "Gamma kit for widget frobnication.")
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )
    tool = _get_tool("search_kit_content")
    result = tool.fn(query="frobnication", limit=5)
    assert result["results"][0]["name"] == "kit-gamma"


def test_search_kit_content_never_raises_for_blank_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path / "empty"})(),
    )
    (tmp_path / "empty").mkdir()
    tool = _get_tool("search_kit_content")
    result = tool.fn(query="", limit=5)
    assert result["results"] == []
