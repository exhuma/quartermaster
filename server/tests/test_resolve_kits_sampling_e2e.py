"""
End-to-end test of ``resolve_kits`` sampling over a real FastMCP session.

Drives the actual MCP wire protocol with an in-memory client that advertises
a sampling handler, proving capability detection and ``ctx.sample`` work
through FastMCP (not just the unit-level fakes). A second client without a
sampling handler proves graceful degradation to the deterministic chain.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastmcp import Client

from app.main import mcp


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def kit_root(tmp_path: Path) -> Path:
    instr = tmp_path / "kit-alpha" / "v1" / "instructions"
    instr.mkdir(parents=True)
    (instr / "invariant.md").write_text(
        "## Invariants\n\nKeep it layered.\n", encoding="utf-8"
    )
    (instr / "index.toml").write_text(
        'summary = "Alpha."\n\n[[sections]]\nfile = "invariant.md"\n'
        'title = "Inv"\ngloss = "g"\nalways_load = true\n',
        encoding="utf-8",
    )
    (tmp_path / "kit-alpha" / "applicability.json").write_text(
        json.dumps(
            {
                "kit_type": "module",
                "summary": "FastAPI backend guidance.",
                "domains": ["backend"],
                "languages": ["python"],
                "frameworks": ["fastapi"],
                "contexts": ["backend"],
                "requires": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
                "excludes": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
                "optional_signals": [],
                "related_kits": [],
                "priority": 70,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture(autouse=True)
def _use_kit_root(kit_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    # No embeddings / configured LLM: the only LLM-grade engine is sampling.
    import app.resolver as resolver

    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [])


async def _sampling_handler(messages, params, context) -> str:
    # The client's "LLM" returns the closed-vocabulary trait JSON.
    return json.dumps({"frameworks": ["fastapi"], "languages": ["python"]})


def test_resolve_kits_uses_client_sampling() -> None:
    async def _go():
        client = Client(mcp, sampling_handler=_sampling_handler)
        async with client:
            return await client.call_tool(
                "resolve_kits", {"task": "build a backend service"}
            )

    data = _run(_go()).data
    assert data["engine"] == "sampling"
    assert "fastapi" in data["inferred_traits"]["frameworks"]
    assert {k["name"] for k in data["kits"]} == {"kit-alpha"}


def test_resolve_kits_degrades_without_sampling() -> None:
    async def _go():
        client = Client(mcp)  # no sampling handler advertised
        async with client:
            return await client.call_tool(
                "resolve_kits", {"task": "add a fastapi endpoint"}
            )

    data = _run(_go()).data
    # Falls back to the deterministic lexical floor.
    assert data["engine"] == "lexical"
    assert "fastapi" in data["inferred_traits"]["frameworks"]


def test_resolve_kits_elicits_on_low_confidence() -> None:
    # A task with no vocabulary overlap → empty traits → low confidence →
    # the server elicits clarification; the handler supplies "fastapi", which
    # the re-resolve picks up lexically and matches kit-alpha.
    async def _elicit(message, response_type, params, context):
        return {"value": "it uses fastapi"}

    async def _go():
        client = Client(mcp, elicitation_handler=_elicit)
        async with client:
            return await client.call_tool(
                "resolve_kits", {"task": "make it better somehow"}
            )

    data = _run(_go()).data
    assert "fastapi" in data["inferred_traits"]["frameworks"]
    assert {k["name"] for k in data["kits"]} == {"kit-alpha"}


def test_resolve_kits_returns_best_effort_when_user_declines() -> None:
    from fastmcp.client.elicitation import ElicitResult

    async def _decline(message, response_type, params, context):
        return ElicitResult(action="decline")

    async def _go():
        client = Client(mcp, elicitation_handler=_decline)
        async with client:
            return await client.call_tool(
                "resolve_kits", {"task": "make it better somehow"}
            )

    data = _run(_go()).data
    # No clarification → best-effort (empty) traits, no crash.
    assert data["inferred_traits"]["frameworks"] == []
