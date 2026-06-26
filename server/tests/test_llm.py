"""
Tests for the optional, pluggable LLM inference layer.

A fake backend stands in for the network so trait inference, the
vocabulary constraint, malformed-output handling, and the fallback wiring
are all exercised offline. One HTTP-shaped test monkeypatches ``httpx`` to
confirm the OpenAI-compatible backend parses content and maps errors.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app import resolver
from app.llm import (
    AnthropicBackend,
    LLMError,
    LLMTraitEngine,
    OpenAICompatBackend,
    get_llm_backend,
)
from app.traits import TraitVocabulary

_VOCAB = TraitVocabulary(
    languages=["python", "typescript"],
    frameworks=["fastapi", "vue"],
    capabilities=["rest-api", "frontend"],
    contexts=["backend", "frontend"],
)


class FakeBackend:
    name = "fake"

    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self._payload = payload
        self._error = error
        self.calls = 0

    def complete_json(self, *, system: str, user: str, timeout: float) -> dict:
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._payload


def _settings(**kw):
    base = {
        "llm_provider": None,
        "llm_base_url": None,
        "llm_model": None,
        "llm_api_key": None,
        "llm_timeout_seconds": 5.0,
    }
    base.update(kw)
    return type("S", (), base)()


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------


def test_get_llm_backend_disabled_by_default() -> None:
    assert get_llm_backend(_settings()) is None


def test_get_llm_backend_openai_requires_base_url_and_model() -> None:
    assert get_llm_backend(_settings(llm_provider="openai")) is None
    backend = get_llm_backend(
        _settings(
            llm_provider="openai",
            llm_base_url="http://localhost:11434/v1",
            llm_model="llama3",
        )
    )
    assert isinstance(backend, OpenAICompatBackend)


def test_get_llm_backend_anthropic_requires_key_and_model() -> None:
    assert get_llm_backend(_settings(llm_provider="anthropic")) is None
    backend = get_llm_backend(
        _settings(
            llm_provider="anthropic",
            llm_api_key="sk-test",
            llm_model="claude-haiku-4-5-20251001",
        )
    )
    assert isinstance(backend, AnthropicBackend)


def test_get_llm_backend_unknown_provider_is_none() -> None:
    assert get_llm_backend(_settings(llm_provider="weird")) is None


# ---------------------------------------------------------------------------
# LLMTraitEngine
# ---------------------------------------------------------------------------


def test_engine_infers_traits_from_backend_json() -> None:
    backend = FakeBackend(
        payload={"frameworks": ["fastapi"], "languages": ["python"]}
    )
    engine = LLMTraitEngine(backend, timeout=5.0)
    result = engine.infer("add a fastapi endpoint", _VOCAB)
    assert result is not None
    assert result.engine == "llm"
    assert "fastapi" in result.frameworks
    assert "python" in result.languages
    assert {p.provenance for p in result.provenance} == {"llm"}


def test_engine_filters_out_of_vocabulary_tokens() -> None:
    backend = FakeBackend(
        payload={
            "frameworks": ["fastapi", "djangoflask"],
            "languages": ["cobol"],
        }
    )
    engine = LLMTraitEngine(backend, timeout=5.0)
    result = engine.infer("task", _VOCAB)
    assert result is not None
    assert result.frameworks == ["fastapi"]
    assert result.languages == []  # cobol not in vocabulary


def test_engine_returns_none_when_all_tokens_out_of_vocabulary() -> None:
    backend = FakeBackend(payload={"languages": ["cobol", "fortran"]})
    engine = LLMTraitEngine(backend, timeout=5.0)
    assert engine.infer("task", _VOCAB) is None


def test_engine_returns_none_on_backend_error() -> None:
    backend = FakeBackend(error=LLMError("boom"))
    engine = LLMTraitEngine(backend, timeout=5.0)
    assert engine.infer("task", _VOCAB) is None


def test_engine_returns_none_on_malformed_shape() -> None:
    backend = FakeBackend(payload=["not", "a", "dict"])
    engine = LLMTraitEngine(backend, timeout=5.0)
    assert engine.infer("task", _VOCAB) is None


def test_engine_rank_sections_delegates_to_section_ranker() -> None:
    backend = FakeBackend(payload={"frameworks": ["fastapi"]})

    class Marker:
        def rank_sections(self, task, refs):
            return [("sentinel", 1.0)]

    engine = LLMTraitEngine(backend, timeout=5.0, section_ranker=Marker())
    assert engine.rank_sections("t", []) == [("sentinel", 1.0)]


# ---------------------------------------------------------------------------
# OpenAI-compatible HTTP backend (httpx monkeypatched)
# ---------------------------------------------------------------------------


def test_openai_backend_parses_content(monkeypatch) -> None:
    captured = {}

    def _fake_request(method, url, **kwargs):
        captured["url"] = url
        body = {
            "choices": [
                {"message": {"content": json.dumps({"frameworks": ["vue"]})}}
            ]
        }
        return httpx.Response(
            200, json=body, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", _fake_request)
    backend = OpenAICompatBackend(
        base_url="http://localhost:11434/v1", model="llama3", api_key="x"
    )
    data = backend.complete_json(system="s", user="u", timeout=5.0)
    assert data == {"frameworks": ["vue"]}
    assert captured["url"].endswith("/chat/completions")


def test_openai_backend_maps_http_error(monkeypatch) -> None:
    def _fake_request(method, url, **kwargs):
        return httpx.Response(
            500, text="boom", request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", _fake_request)
    backend = OpenAICompatBackend(
        base_url="http://localhost/v1", model="m", api_key=None
    )
    with pytest.raises(LLMError):
        backend.complete_json(system="s", user="u", timeout=1.0)


def test_openai_backend_maps_bad_json(monkeypatch) -> None:
    def _fake_request(method, url, **kwargs):
        body = {"choices": [{"message": {"content": "not json"}}]}
        return httpx.Response(
            200, json=body, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(httpx, "request", _fake_request)
    backend = OpenAICompatBackend(
        base_url="http://localhost/v1", model="m", api_key=None
    )
    with pytest.raises(LLMError):
        backend.complete_json(system="s", user="u", timeout=1.0)


# ---------------------------------------------------------------------------
# Resolver integration (fallback ordering)
# ---------------------------------------------------------------------------


def _kit_root(tmp_path: Path) -> Path:
    instr = tmp_path / "kit-alpha" / "v1" / "instructions"
    instr.mkdir(parents=True)
    (instr / "invariant.md").write_text("## Inv\n", encoding="utf-8")
    (instr / "index.toml").write_text(
        'summary = "s"\n\n[[sections]]\nfile = "invariant.md"\n'
        'title = "Inv"\ngloss = "g"\nalways_load = true\n',
        encoding="utf-8",
    )
    (tmp_path / "kit-alpha" / "applicability.json").write_text(
        json.dumps(
            {
                "kit_type": "module",
                "summary": "FastAPI backend.",
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


def test_pipeline_uses_llm_then_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _kit_root(tmp_path)
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": root})(),
    )

    # LLM wins when it returns in-vocabulary traits.
    good = LLMTraitEngine(
        FakeBackend(payload={"frameworks": ["fastapi"]}), timeout=5.0
    )
    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [good])
    out = resolver.resolve_kits(task="anything")
    assert out["engine"] == "llm"

    # When the LLM errors, resolution degrades to the lexical floor.
    bad = LLMTraitEngine(FakeBackend(error=LLMError("down")), timeout=5.0)
    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [bad])
    out = resolver.resolve_kits(task="build a fastapi service")
    assert out["engine"] == "lexical"
