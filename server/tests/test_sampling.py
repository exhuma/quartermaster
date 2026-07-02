"""
Tests for the MCP-sampling trait engine and capability helpers.

A fake Context stands in for the client connection so the engine's prompt
construction, JSON parsing, vocabulary constraint, and graceful-degradation
paths are all exercised offline.
"""

from __future__ import annotations

import asyncio
import json

import mcp.types as mcp_types
from mcp.shared.exceptions import McpError

from app.sampling import (
    SamplingTraitEngine,
    client_supports_elicitation,
    client_supports_sampling,
)
from app.traits import TraitVocabulary

_VOCAB = TraitVocabulary(
    languages=["python", "typescript"],
    frameworks=["fastapi", "vue"],
    capabilities=["rest-api", "frontend"],
    contexts=["backend", "frontend"],
)


class _FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeSession:
    def __init__(self, *, sampling: bool, elicitation: bool) -> None:
        self._sampling = sampling
        self._elicitation = elicitation

    def check_client_capability(
        self, capability: mcp_types.ClientCapabilities
    ) -> bool:
        if capability.sampling is not None:
            return self._sampling
        if capability.elicitation is not None:
            return self._elicitation
        return False


class _FakeContext:
    def __init__(
        self,
        *,
        text: str | None = None,
        error: Exception | None = None,
        sampling: bool = True,
        elicitation: bool = True,
    ) -> None:
        self._text = text
        self._error = error
        self.session = _FakeSession(
            sampling=sampling, elicitation=elicitation
        )
        self.sample_calls: list[dict] = []

    async def sample(self, messages, **kwargs):
        self.sample_calls.append({"messages": messages, **kwargs})
        if self._error is not None:
            raise self._error
        return _FakeResult(self._text or "")


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# SamplingTraitEngine.infer_async
# ---------------------------------------------------------------------------


def test_sampling_infers_in_vocabulary_traits() -> None:
    ctx = _FakeContext(
        text=json.dumps({"frameworks": ["fastapi"], "languages": ["python"]})
    )
    engine = SamplingTraitEngine()
    result = _run(engine.infer_async("add a fastapi endpoint", _VOCAB, ctx))
    assert result is not None
    assert result.engine == "sampling"
    assert result.frameworks == ["fastapi"]
    assert result.languages == ["python"]
    assert {p.provenance for p in result.provenance} == {"sampling"}
    # The system prompt is forwarded so the model is constrained.
    assert ctx.sample_calls[0]["system_prompt"]


def test_sampling_returns_none_on_out_of_vocabulary() -> None:
    ctx = _FakeContext(text=json.dumps({"languages": ["cobol"]}))
    engine = SamplingTraitEngine()
    assert _run(engine.infer_async("task", _VOCAB, ctx)) is None


def test_sampling_returns_none_on_bad_json() -> None:
    ctx = _FakeContext(text="not json at all")
    engine = SamplingTraitEngine()
    assert _run(engine.infer_async("task", _VOCAB, ctx)) is None


def test_sampling_returns_none_on_mcp_error() -> None:
    err = McpError(
        mcp_types.ErrorData(code=-32603, message="sampling unsupported")
    )
    ctx = _FakeContext(error=err)
    engine = SamplingTraitEngine()
    assert _run(engine.infer_async("task", _VOCAB, ctx)) is None


def test_sampling_returns_none_on_unexpected_error() -> None:
    ctx = _FakeContext(error=RuntimeError("boom"))
    engine = SamplingTraitEngine()
    assert _run(engine.infer_async("task", _VOCAB, ctx)) is None


def test_sampling_prompt_includes_memory_hint_when_provided() -> None:
    ctx = _FakeContext(
        text=json.dumps({"frameworks": ["fastapi"], "languages": ["python"]})
    )
    engine = SamplingTraitEngine()
    hint = "Recurring context for this user: python, fastapi (advisory only)."
    _run(engine.infer_async("add a fastapi endpoint", _VOCAB, ctx, hint=hint))
    assert hint in ctx.sample_calls[0]["messages"]


def test_sampling_prompt_omits_hint_section_when_absent() -> None:
    ctx = _FakeContext(
        text=json.dumps({"frameworks": ["fastapi"], "languages": ["python"]})
    )
    engine = SamplingTraitEngine()
    _run(engine.infer_async("add a fastapi endpoint", _VOCAB, ctx))
    assert "advisory only" not in ctx.sample_calls[0]["messages"]


# ---------------------------------------------------------------------------
# Capability helpers
# ---------------------------------------------------------------------------


def test_client_supports_sampling_reflects_capability() -> None:
    assert client_supports_sampling(_FakeContext(sampling=True)) is True
    assert client_supports_sampling(_FakeContext(sampling=False)) is False


def test_client_supports_elicitation_reflects_capability() -> None:
    assert (
        client_supports_elicitation(_FakeContext(elicitation=True)) is True
    )
    assert (
        client_supports_elicitation(_FakeContext(elicitation=False)) is False
    )


def test_capability_helpers_are_defensive_on_error() -> None:
    class _Broken:
        @property
        def session(self):
            raise RuntimeError("no session")

    assert client_supports_sampling(_Broken()) is False
    assert client_supports_elicitation(_Broken()) is False
