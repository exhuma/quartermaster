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
    kit_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_settings = type(
        "S",
        (),
        {
            "kits_root": kit_root,
            "private_kits_root": tmp_path / "private-kits",
        },
    )()
    monkeypatch.setattr("app.kits.get_settings", lambda: fake_settings)
    # Authenticated-caller resolves also consult the private-kit overlay,
    # which reads settings independently of app.kits.get_settings.
    monkeypatch.setattr("app.private_kits.get_settings", lambda: fake_settings)
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
        "gap",
    }
    traits = out["inferred_traits"]
    assert set(traits) >= {
        "languages",
        "frameworks",
        "capabilities",
        "contexts",
        "provenance",
    }


def test_gap_is_none_when_traits_were_inferred() -> None:
    # A task with a real trait match must never even reach the catalog-recall
    # check (no wasted cost on the normal, well-covered path).
    def _boom(**kwargs):
        raise AssertionError(
            "detect_gap must not run when traits were inferred"
        )

    import app.gap as gap_module

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gap_module, "detect_gap", _boom)
        mp.setattr(resolver, "detect_gap", _boom)
        out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    assert out["gap"] is None


def test_gap_detected_surfaces_in_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gap import GapSignal

    signal = GapSignal(
        task="train a pytorch model on GPUs",
        best_recall_score=0.05,
        matched_traits=["python"],
        reason="no-catalog-match",
    )
    monkeypatch.setattr(resolver, "detect_gap", lambda **_: signal)

    calls: list[str] = []
    monkeypatch.setattr(
        resolver.telemetry, "record_gap_detected", lambda: calls.append("x")
    )

    out = resolver.resolve_kits(task="train a pytorch model on GPUs")
    assert out["gap"] is not None
    assert out["gap"]["detected"] is True
    assert out["gap"]["reason"] == "no-catalog-match"
    assert out["gap"]["discovered_traits"] == ["python"]
    assert out["gap"]["recall_score"] == 0.05
    assert out["gap"]["suggested_summary"] == "train a pytorch model on GPUs"
    assert calls == ["x"]


def test_gap_none_when_detect_gap_finds_a_real_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The catalog-recall pass found a real match -> not a gap, and the
    # telemetry counter must not fire.
    monkeypatch.setattr(resolver, "detect_gap", lambda **_: None)

    calls: list[str] = []
    monkeypatch.setattr(
        resolver.telemetry, "record_gap_detected", lambda: calls.append("x")
    )

    out = resolver.resolve_kits(task="train a pytorch model on GPUs")
    assert out["gap"] is None
    assert calls == []


def test_gap_file_hint_reflects_backend_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gap import GapSignal

    signal = GapSignal(
        task="train a pytorch model on GPUs",
        best_recall_score=0.0,
        matched_traits=[],
        reason="no-catalog-match",
    )
    monkeypatch.setattr(resolver, "detect_gap", lambda **_: signal)

    monkeypatch.setattr(resolver, "gap_tools_enabled", lambda: False)
    out = resolver.resolve_kits(task="train a pytorch model on GPUs")
    assert "No issue backend configured" in out["gap"]["file_hint"]

    monkeypatch.setattr(resolver, "gap_tools_enabled", lambda: True)
    out = resolver.resolve_kits(task="train a pytorch model on GPUs")
    assert "request_clarification_or_addition" in out["gap"]["file_hint"]


def test_gap_suggested_title_is_truncated_for_long_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.gap import GapSignal

    long_task = "train a pytorch model on GPUs " * 10
    signal = GapSignal(
        task=long_task,
        best_recall_score=0.0,
        matched_traits=[],
        reason="no-catalog-match",
    )
    monkeypatch.setattr(resolver, "detect_gap", lambda **_: signal)

    out = resolver.resolve_kits(task=long_task)
    assert len(out["gap"]["suggested_title"]) <= 80
    assert out["gap"]["suggested_summary"] == long_task


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


def test_local_store_records_authenticated_subject_and_traits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.identity import reset_identity, set_identity

    captured: dict = {}
    monkeypatch.setattr(
        resolver.local_store,
        "record_resolve",
        lambda **kwargs: captured.update(kwargs),
    )

    tokens = set_identity("alice", "Alice")
    try:
        resolver.resolve_kits(task="add a FastAPI REST endpoint")
    finally:
        reset_identity(tokens)

    assert captured["subject"] == "alice"
    traits = json.loads(captured["traits_json"])
    assert "fastapi" in traits["frameworks"]


def test_local_store_records_no_subject_when_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        resolver.local_store,
        "record_resolve",
        lambda **kwargs: captured.update(kwargs),
    )

    resolver.resolve_kits(task="add a FastAPI REST endpoint")
    assert captured["subject"] is None


def _fake_memory_settings(**overrides):
    base = dict(
        user_memory_enabled=True,
        user_memory_store_path="/tmp/does-not-matter.toml",
        user_memory_ttl_seconds=3600,
        user_memory_half_life_days=30.0,
        user_memory_top_domains=5,
        user_memory_top_kits=5,
        user_memory_top_languages=3,
        user_memory_top_frameworks=3,
    )
    base.update(overrides)
    return type("S", (), base)()


def test_memory_nudge_applied_when_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.identity import reset_identity, set_identity

    monkeypatch.setattr(resolver, "get_settings", _fake_memory_settings)
    monkeypatch.setattr(resolver.local_store, "get_store", lambda: object())
    monkeypatch.setattr(
        "app.resolver.user_memory.get_or_build",
        lambda *a, **k: {"top_kits": ["kit-alpha"]},
    )

    def fake_nudge(candidates, profile):
        assert profile == {"top_kits": ["kit-alpha"]}
        return [{**c, "score": 999} for c in candidates]

    monkeypatch.setattr(resolver, "apply_memory_nudge", fake_nudge)

    tokens = set_identity("alice", "Alice")
    try:
        out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    finally:
        reset_identity(tokens)

    assert out["kits"][0]["score"] == 999


def test_memory_nudge_skipped_when_unauthenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(resolver, "get_settings", _fake_memory_settings)
    monkeypatch.setattr(resolver.local_store, "get_store", lambda: object())

    def _boom(*a, **k):
        raise AssertionError(
            "apply_memory_nudge must not run when unauthenticated"
        )

    monkeypatch.setattr(resolver, "apply_memory_nudge", _boom)

    resolver.resolve_kits(task="add a FastAPI REST endpoint")  # must not raise


def test_memory_nudge_skipped_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.identity import reset_identity, set_identity

    monkeypatch.setattr(
        resolver,
        "get_settings",
        lambda: _fake_memory_settings(user_memory_enabled=False),
    )

    def _boom(*a, **k):
        raise AssertionError("apply_memory_nudge must not run when disabled")

    monkeypatch.setattr(resolver, "apply_memory_nudge", _boom)

    tokens = set_identity("alice", "Alice")
    try:
        resolver.resolve_kits(task="add a FastAPI REST endpoint")
    finally:
        reset_identity(tokens)


def test_memory_nudge_skipped_when_no_local_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.identity import reset_identity, set_identity

    monkeypatch.setattr(resolver, "get_settings", _fake_memory_settings)
    monkeypatch.setattr(resolver.local_store, "get_store", lambda: None)

    def _boom(*a, **k):
        raise AssertionError("apply_memory_nudge must not run without a store")

    monkeypatch.setattr(resolver, "apply_memory_nudge", _boom)

    tokens = set_identity("alice", "Alice")
    try:
        # must not raise
        resolver.resolve_kits(task="add a FastAPI REST endpoint")
    finally:
        reset_identity(tokens)


def test_memory_nudge_tolerates_settings_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import ValidationError

    from app.identity import reset_identity, set_identity

    def _raise():
        raise ValidationError.from_exception_data("Settings", [])

    monkeypatch.setattr(resolver, "get_settings", _raise)

    def _boom(*a, **k):
        raise AssertionError(
            "apply_memory_nudge must not run on settings error"
        )

    monkeypatch.setattr(resolver, "apply_memory_nudge", _boom)

    tokens = set_identity("alice", "Alice")
    try:
        # must not raise
        resolver.resolve_kits(task="add a FastAPI REST endpoint")
    finally:
        reset_identity(tokens)
