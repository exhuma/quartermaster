"""Tests for the ``resolve_kits`` MCP tool wrapper and its instructions.

The wrapper is async: it prefers MCP sampling for trait inference when the
connecting client supports it, then delegates the (synchronous) selection +
assembly to :func:`app.resolver.resolve_kits` in a worker thread.
"""

from __future__ import annotations

import asyncio

import pytest

from app.main import MCP_INSTRUCTIONS, mcp
from app.resolver import InferredTrait, InferredTraits


def _get_tool(name: str):
    return asyncio.run(mcp.get_tool(name))


def _run(coro):
    return asyncio.run(coro)


class _FakeSession:
    def __init__(self, *, sampling: bool, elicitation: bool = False) -> None:
        self._sampling = sampling
        self._elicitation = elicitation

    def check_client_capability(self, capability) -> bool:
        if capability.sampling is not None:
            return self._sampling
        if capability.elicitation is not None:
            return self._elicitation
        return False


class _FakeCtx:
    """Minimal stand-in for the FastMCP Context in unit tests."""

    def __init__(
        self, *, sampling: bool = False, elicitation: bool = False
    ) -> None:
        self.session = _FakeSession(
            sampling=sampling, elicitation=elicitation
        )


def test_resolve_kits_tool_is_registered() -> None:
    tool = _get_tool("resolve_kits")
    assert tool is not None
    assert tool.fn is not None


def test_resolve_kits_without_ctx_delegates_without_pre_inferred(
    monkeypatch,
) -> None:
    tool = _get_tool("resolve_kits")
    sentinel = {"engine": "lexical", "kits": []}
    captured: dict = {}

    def _fake_resolve(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr("app.main._resolve_kits", _fake_resolve)
    result = _run(tool.fn(task="add a FastAPI endpoint", limit=3))
    assert result is sentinel
    assert captured["task"] == "add a FastAPI endpoint"
    assert captured["limit"] == 3
    # No client context → no sampling → no pre-inferred traits.
    assert captured["pre_inferred"] is None


def test_resolve_kits_threads_sampled_traits_as_pre_inferred(
    monkeypatch,
) -> None:
    tool = _get_tool("resolve_kits")
    captured: dict = {}
    sampled = InferredTraits(
        languages=["python"],
        frameworks=["fastapi"],
        capabilities=[],
        contexts=[],
        provenance=[InferredTrait("frameworks", "fastapi", "sampling")],
        engine="sampling",
    )

    async def _fake_sampling(task, ctx, settings):
        return sampled

    def _fake_resolve(**kwargs):
        captured.update(kwargs)
        return {"engine": kwargs["pre_inferred"].engine, "kits": []}

    monkeypatch.setattr("app.main._infer_via_sampling", _fake_sampling)
    monkeypatch.setattr("app.main._resolve_kits", _fake_resolve)
    monkeypatch.setattr("app.main.build_ranker", lambda: "ranker-sentinel")

    result = _run(tool.fn(task="add auth", ctx=_FakeCtx(sampling=True)))
    assert result["engine"] == "sampling"
    assert captured["pre_inferred"] is sampled
    assert captured["section_ranker"] == "ranker-sentinel"


def test_resolve_kits_falls_back_when_sampling_yields_nothing(
    monkeypatch,
) -> None:
    tool = _get_tool("resolve_kits")
    captured: dict = {}

    async def _no_traits(task, ctx, settings):
        return None

    def _fake_resolve(**kwargs):
        captured.update(kwargs)
        return {"engine": "lexical", "kits": []}

    monkeypatch.setattr("app.main._infer_via_sampling", _no_traits)
    monkeypatch.setattr("app.main._resolve_kits", _fake_resolve)
    _run(tool.fn(task="do something", ctx=_FakeCtx(sampling=True)))
    # Sampling produced nothing → resolver runs its own inference chain.
    assert captured["pre_inferred"] is None


def test_resolve_kits_wrapper_maps_value_error(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")

    def _raise(**kwargs):
        raise ValueError("task must not be empty")

    monkeypatch.setattr("app.main._resolve_kits", _raise)
    with pytest.raises(ValueError, match="task"):
        _run(tool.fn(task=""))


# ---------------------------------------------------------------------------
# Elicitation
# ---------------------------------------------------------------------------


def test_empty_task_elicits_when_supported(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    captured: dict = {}

    async def _fake_elicit(ctx, message):
        return "build a fastapi service"

    def _fake_resolve(**kwargs):
        captured.update(kwargs)
        return {
            "engine": "lexical",
            "kits": [],
            "confidence": 0.9,
            "broadening_recommended": False,
            "inferred_traits": {
                "languages": [],
                "frameworks": ["fastapi"],
                "capabilities": [],
                "contexts": [],
            },
        }

    monkeypatch.setattr("app.main._elicit_text", _fake_elicit)
    monkeypatch.setattr("app.main._resolve_kits", _fake_resolve)
    _run(tool.fn(task="   ", ctx=_FakeCtx(elicitation=True)))
    # The elicited task replaced the empty one.
    assert captured["task"] == "build a fastapi service"


def test_empty_task_raises_when_elicitation_unsupported(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")

    def _raise(**kwargs):
        raise ValueError("task must not be empty")

    monkeypatch.setattr("app.main._resolve_kits", _raise)
    # ctx present but client does not support elicitation → legacy behaviour.
    with pytest.raises(ValueError, match="task"):
        _run(tool.fn(task="", ctx=_FakeCtx(elicitation=False)))


def test_low_confidence_elicits_and_reresolves(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    calls: list[str] = []

    async def _fake_resolve_once(task, **kwargs):
        calls.append(task)
        if len(calls) == 1:
            return {
                "engine": "lexical",
                "kits": [],
                "confidence": 0.1,
                "broadening_recommended": True,
                "inferred_traits": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
            }
        return {
            "engine": "lexical",
            "kits": [{"name": "kit-alpha"}],
            "confidence": 0.9,
            "broadening_recommended": False,
            "inferred_traits": {
                "languages": ["python"],
                "frameworks": ["fastapi"],
                "capabilities": [],
                "contexts": [],
            },
        }

    async def _fake_elicit(ctx, message):
        return "it's a python fastapi backend"

    monkeypatch.setattr("app.main._resolve_once", _fake_resolve_once)
    monkeypatch.setattr("app.main._elicit_text", _fake_elicit)
    result = _run(tool.fn(task="do stuff", ctx=_FakeCtx(elicitation=True)))
    # Re-resolved once with the enriched task.
    assert len(calls) == 2
    assert "do stuff" in calls[1]
    assert "python fastapi" in calls[1]
    assert result["confidence"] == 0.9


def test_low_confidence_no_reresolve_when_user_declines(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    calls: list[str] = []

    async def _fake_resolve_once(task, **kwargs):
        calls.append(task)
        return {
            "engine": "lexical",
            "kits": [],
            "confidence": 0.1,
            "broadening_recommended": True,
            "inferred_traits": {
                "languages": [],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
        }

    async def _decline(ctx, message):
        return None  # user declined / cancelled

    monkeypatch.setattr("app.main._resolve_once", _fake_resolve_once)
    monkeypatch.setattr("app.main._elicit_text", _decline)
    result = _run(tool.fn(task="do stuff", ctx=_FakeCtx(elicitation=True)))
    # No second resolve: best-effort first result is returned.
    assert len(calls) == 1
    assert result["confidence"] == 0.1


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


def _full_result() -> dict:
    return {
        "engine": "sampling",
        "inferred_traits": {
            "languages": ["python"],
            "frameworks": ["fastapi"],
            "capabilities": ["authentication"],
            "contexts": [],
            "provenance": [
                {
                    "category": "capabilities",
                    "value": "authentication",
                    "source": "sampling",
                }
            ],
        },
        "confidence": 0.82,
        "coverage": 0.75,
        "broadening_recommended": False,
        "kits": [
            {
                "name": "module-auth-oidc",
                "version": "v1",
                "score": 92,
                "confidence": "high",
                "reasons": ["match:capabilities"],
                "summary": "OIDC auth",
                "sections": [],
                "always_load_markdown": "",
                "fetch_on_demand": [],
            }
        ],
        "warnings": [],
    }


def test_include_diagnostics_attaches_diagnostics_block(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    monkeypatch.setattr("app.main._resolve_kits", lambda **k: _full_result())

    result = _run(tool.fn(task="add JWT auth", include_diagnostics=True))

    diag = result["_diagnostics"]
    assert diag["engine"] == "sampling"
    assert diag["coverage"] == 0.75
    assert diag["selection_confidence"] == 0.82
    assert diag["clarification_used"] is False
    assert diag["trait_provenance"] == [
        {
            "category": "capabilities",
            "value": "authentication",
            "source": "sampling",
        }
    ]
    assert diag["kit_scores"] == [
        {
            "name": "module-auth-oidc",
            "score": 92,
            "confidence": "high",
            "reasons": ["match:capabilities"],
        }
    ]
    assert "Quartermaster Insights" in diag["report_instruction"]


def test_diagnostics_absent_by_default(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    monkeypatch.setattr("app.main._resolve_kits", lambda **k: _full_result())

    result = _run(tool.fn(task="add JWT auth"))

    assert "_diagnostics" not in result


def test_diagnostics_reports_clarification_used(monkeypatch) -> None:
    tool = _get_tool("resolve_kits")
    calls: list[str] = []

    async def _fake_resolve_once(task, **kwargs):
        calls.append(task)
        if len(calls) == 1:
            return {
                **_full_result(),
                "confidence": 0.1,
                "broadening_recommended": True,
                "inferred_traits": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                    "provenance": [],
                },
            }
        return _full_result()

    async def _fake_elicit(ctx, message):
        return "python fastapi backend"

    monkeypatch.setattr("app.main._resolve_once", _fake_resolve_once)
    monkeypatch.setattr("app.main._elicit_text", _fake_elicit)

    result = _run(
        tool.fn(
            task="do stuff",
            include_diagnostics=True,
            ctx=_FakeCtx(elicitation=True),
        )
    )

    assert len(calls) == 2
    assert result["_diagnostics"]["clarification_used"] is True


def test_instructions_point_at_one_shot_tool() -> None:
    assert "resolve_kits" in MCP_INSTRUCTIONS
