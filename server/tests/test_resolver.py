"""
Tests for the one-shot ``resolve_kits`` pipeline (lexical baseline).

These cover the deterministic floor: turning a task string into trait
lists with no embeddings/LLM, feeding the existing ``select_kits_v2``
scorer unchanged, and assembling the hybrid response (recommendation +
inlined ``always_load`` content + on-demand section ids).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import resolver


def _write_kit_version(
    base: Path,
    kit: str,
    ver: str,
    summary: str,
    sections: list[dict],
) -> None:
    instr = base / kit / ver / "instructions"
    instr.mkdir(parents=True)
    lines = [f'summary = "{summary}"', ""]
    for s in sections:
        (instr / s["file"]).write_text(s["body"], encoding="utf-8")
        lines += [
            "[[sections]]",
            f'file = "{s["file"]}"',
            f'title = "{s["title"]}"',
            f'gloss = "{s.get("gloss", s["title"])}"',
            f'always_load = {"true" if s.get("always_load") else "false"}',
            "",
        ]
    (instr / "index.toml").write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(base: Path, kit: str, manifest: dict) -> None:
    (base / kit / "applicability.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


@pytest.fixture()
def kit_root(tmp_path: Path) -> Path:
    _write_kit_version(
        tmp_path,
        "kit-alpha",
        "v1",
        summary="Alpha summary.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Architecture invariants",
                "gloss": "Non-negotiables for FastAPI layering",
                "always_load": True,
                "body": "## Invariants\n\nKeep it layered.\n",
            },
            {
                "file": "endpoints.md",
                "title": "REST endpoints",
                "gloss": "How to add a REST API endpoint route",
                "body": "## Endpoints\n\nAdd routers.\n",
            },
            {
                "file": "testing.md",
                "title": "Testing",
                "gloss": "Pytest setup and fixtures",
                "body": "## Testing\n\nUse pytest.\n",
            },
        ],
    )
    _write_manifest(
        tmp_path,
        "kit-alpha",
        {
            "kit_type": "module",
            "summary": "FastAPI backend guidance for Python services.",
            "domains": ["api-design", "backend"],
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
            "optional_signals": ["rest-api", "async"],
            "related_kits": [],
            "priority": 70,
        },
    )
    return tmp_path


@pytest.fixture(autouse=True)
def _use_kit_root(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    # No embeddings, no LLM: force the lexical floor for these tests.
    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [])


def test_empty_task_raises() -> None:
    with pytest.raises(ValueError):
        resolver.resolve_kits(task="   ")


def test_response_has_full_schema() -> None:
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    assert out["engine"] == "lexical"
    assert set(out) >= {
        "engine",
        "inferred_traits",
        "confidence",
        "coverage",
        "broadening_recommended",
        "kits",
        "warnings",
    }
    traits = out["inferred_traits"]
    assert set(traits) >= {
        "languages",
        "frameworks",
        "capabilities",
        "contexts",
        "provenance",
    }


def test_lexical_infers_framework_from_task_text() -> None:
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    assert "fastapi" in out["inferred_traits"]["frameworks"]
    # provenance records the source for each inferred trait
    sources = {p["source"] for p in out["inferred_traits"]["provenance"]}
    assert sources == {"lexical"}
    values = {p["value"] for p in out["inferred_traits"]["provenance"]}
    assert "fastapi" in values


def test_hybrid_assembly_inlines_always_load_and_lists_rest() -> None:
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    kits = {k["name"]: k for k in out["kits"]}
    assert "kit-alpha" in kits
    alpha = kits["kit-alpha"]
    # always_load content is inlined...
    assert "Keep it layered." in alpha["always_load_markdown"]
    # ...and the always_load section is not offered for on-demand fetch.
    assert "invariant" not in alpha["fetch_on_demand"]
    # the relevant non-always_load section ("endpoints") is offered.
    assert "endpoints" in alpha["fetch_on_demand"]
    # section descriptors carry the always_load flag
    by_id = {s["id"]: s for s in alpha["sections"]}
    assert by_id["invariant"]["always_load"] is True
    assert by_id["endpoints"]["always_load"] is False


def test_irrelevant_sections_are_not_offered() -> None:
    # "testing" has no lexical overlap with the task -> not surfaced.
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    alpha = {k["name"]: k for k in out["kits"]}["kit-alpha"]
    assert "testing" not in alpha["fetch_on_demand"]


def test_max_sections_per_kit_bounds_on_demand_list() -> None:
    out = resolver.resolve_kits(
        task="add a FastAPI REST endpoint route api", max_sections_per_kit=1
    )
    alpha = {k["name"]: k for k in out["kits"]}["kit-alpha"]
    assert len(alpha["fetch_on_demand"]) <= 1


def test_build_ranker_returns_a_section_ranker() -> None:
    # With no embeddings/LLM configured (autouse fixture) the ranker is the
    # lexical floor, but it always exposes the ranking contract.
    ranker = resolver.build_ranker()
    assert hasattr(ranker, "rank_sections")


def test_pre_inferred_skips_inference_and_uses_provided_traits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom(*args, **kwargs):
        raise AssertionError("_infer must not run when pre_inferred is given")

    monkeypatch.setattr(resolver, "_infer", _boom)
    pre = resolver.InferredTraits(
        languages=["python"],
        frameworks=["fastapi"],
        capabilities=[],
        contexts=[],
        provenance=[
            resolver.InferredTrait("frameworks", "fastapi", "sampling")
        ],
        engine="sampling",
    )
    out = resolver.resolve_kits(task="anything", pre_inferred=pre)
    assert out["engine"] == "sampling"
    assert "fastapi" in out["inferred_traits"]["frameworks"]
    sources = {p["source"] for p in out["inferred_traits"]["provenance"]}
    assert sources == {"sampling"}
    # The recommendation still assembles (sections ranked by the fallback
    # ranker, content inlined).
    alpha = {k["name"]: k for k in out["kits"]}["kit-alpha"]
    assert "Keep it layered." in alpha["always_load_markdown"]


def test_scorer_is_called_with_inferred_traits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    real = resolver.select_kits_v2

    def _spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(resolver, "select_kits_v2", _spy)
    resolver.resolve_kits(task="add a FastAPI REST endpoint")
    assert "fastapi" in captured["frameworks"]
