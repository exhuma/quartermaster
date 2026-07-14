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
        "clarification",
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


def _db_kit_requiring_language(base: Path, langs: list[str]) -> None:
    """Write a database kit that hard-requires a language into *base*."""
    _write_kit_version(
        base,
        "kit-db",
        "v1",
        summary="Database kit.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Database invariants",
                "gloss": "Non-negotiables for database access",
                "always_load": True,
                "body": "## Invariants\n\nUse migrations.\n",
            },
        ],
    )
    _write_manifest(
        base,
        "kit-db",
        {
            "kit_type": "module",
            "summary": "Database access guidance.",
            "domains": ["database"],
            "languages": langs,
            "frameworks": [],
            "contexts": ["backend"],
            "requires": {
                "languages": langs,
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
        },
    )


def test_clarification_surfaces_in_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.clarify import ClarifyQuestion, ClarifySignal

    signal = ClarifySignal(
        questions=[
            ClarifyQuestion(
                category="languages",
                options=["csharp", "python"],
                blocking_kits=["kit-db"],
                why="kit-db requires a specific language.",
            )
        ],
        reason="pivotal-trait-missing",
    )
    monkeypatch.setattr(resolver, "detect_clarification", lambda **_: signal)

    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    block = out["clarification"]
    assert block is not None
    assert block["needed"] is True
    assert block["reason"] == "pivotal-trait-missing"
    assert "how_to_answer" in block
    question = block["questions"][0]
    assert question["category"] == "languages"
    assert question["options"] == ["csharp", "python"]
    assert question["blocking_kits"] == ["kit-db"]
    assert question["question"]  # human-facing text present
    assert question["hint"]  # repo-inspection hint present


def test_clarification_not_run_when_no_inference() -> None:
    # Mutual exclusion with the gap path: when nothing is inferred, the
    # clarification detector must not even run (gap detection handles it).
    def _boom(**kwargs):
        raise AssertionError(
            "detect_clarification must not run when nothing was inferred"
        )

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(resolver, "detect_clarification", _boom)
        mp.setattr(resolver, "detect_gap", lambda **_: None)
        out = resolver.resolve_kits(task="train a pytorch model on GPUs")
    assert out["clarification"] is None


def _enable_clarification(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_settings() ValidationErrors in the test env (Keycloak vars unset),
    # so the detector would treat the feature as off — mirror test_gap and
    # stub the settings it reads. Production has real settings.
    from types import SimpleNamespace

    monkeypatch.setattr(
        "app.clarify.get_settings",
        lambda: SimpleNamespace(
            clarification_enabled=True,
            clarification_max_questions=2,
            clarification_min_blocking_kits=1,
        ),
    )


def test_clarification_end_to_end_for_missing_language(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A db kit hard-requires a language; the task infers the `database`
    # capability but no language -> a real clarification for `languages`.
    _enable_clarification(monkeypatch)
    _db_kit_requiring_language(kit_root, ["python", "csharp"])
    out = resolver.resolve_kits(task="add a database")
    assert out["inferred_traits"]["capabilities"] == ["database"]
    assert out["inferred_traits"]["languages"] == []
    block = out["clarification"]
    assert block is not None
    categories = [q["category"] for q in block["questions"]]
    assert "languages" in categories
    lang_q = next(q for q in block["questions"] if q["category"] == "languages")
    assert lang_q["options"] == ["csharp", "python"]


def test_clarification_cleared_once_language_folded_in(
    kit_root: Path,
) -> None:
    # The loop-breaker: re-resolving with the language in the task clears the
    # clarification (the dimension is now inferred).
    _db_kit_requiring_language(kit_root, ["python", "csharp"])
    out = resolver.resolve_kits(task="add a database using python")
    assert "python" in out["inferred_traits"]["languages"]
    assert out["clarification"] is None


def test_policy_kit_injected_on_every_resolve(kit_root: Path) -> None:
    # A global policy kit (always_apply, no requires) is delivered even for a
    # task that does not match it on traits.
    _write_kit_version(
        kit_root,
        "kit-policy",
        "v1",
        summary="Policy kit.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Global policy",
                "gloss": "Baseline rules for every project",
                "always_load": True,
                "body": "## Policy\n\nAlways sign commits.\n",
            },
        ],
    )
    _write_manifest(
        kit_root,
        "kit-policy",
        {
            "kit_type": "module",
            "summary": "Baseline policy for every project.",
            "domains": ["governance"],
            "languages": [],
            "frameworks": [],
            "contexts": [],
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
            "priority": 10,
            "always_apply": True,
        },
    )
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    by_name = {kit["name"]: kit for kit in out["kits"]}
    assert "kit-policy" in by_name
    assert by_name["kit-policy"]["policy"] is True
    markdown = by_name["kit-policy"]["always_load_markdown"]
    assert "Always sign commits" in markdown


def test_pending_policy_kit_withholds_content(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A project-type policy kit that requires a language it doesn't know is
    # surfaced as pending (no body) and drives a language clarification.
    _enable_clarification(monkeypatch)
    _write_kit_version(
        kit_root,
        "kit-py-policy",
        "v1",
        summary="Python policy kit.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Python policy",
                "gloss": "Baseline rules for Python projects",
                "always_load": True,
                "body": "## Policy\n\nUse ruff.\n",
            },
        ],
    )
    _write_manifest(
        kit_root,
        "kit-py-policy",
        {
            "kit_type": "module",
            "summary": "Baseline policy for Python projects.",
            "domains": ["governance"],
            "languages": ["python"],
            "frameworks": [],
            "contexts": [],
            "requires": {
                "languages": ["python"],
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
            "priority": 10,
            "always_apply": True,
        },
    )
    # A task that infers a trait (so inference is non-empty and clarification
    # runs) but no language: the python policy kit stays pending.
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    assert out["inferred_traits"]["languages"] == []
    by_name = {kit["name"]: kit for kit in out["kits"]}
    assert "kit-py-policy" in by_name
    pending = by_name["kit-py-policy"]
    assert pending["policy_pending"] is True
    assert pending["always_load_markdown"] == ""
    # And the missing language is surfaced for clarification.
    assert out["clarification"] is not None


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


# ---------------------------------------------------------------------------
# Version pinning in the one-shot resolve pipeline
# ---------------------------------------------------------------------------


def _add_kit_alpha_v2(kit_root: Path) -> None:
    """Promote the fixture's single-version kit-alpha to v1 + v2 + changelog."""
    _write_kit_version(
        kit_root,
        "kit-alpha",
        "v2",
        summary="Alpha v2 summary.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Architecture invariants",
                "gloss": "Non-negotiables for FastAPI layering",
                "always_load": True,
                "body": "## Invariants\n\nKeep it layered (v2).\n",
            },
            {
                "file": "endpoints.md",
                "title": "REST endpoints",
                "gloss": "How to add a REST API endpoint route",
                "body": "## Endpoints\n\nAdd routers (v2).\n",
            },
        ],
    )
    (kit_root / "kit-alpha" / "CHANGELOG.md").write_text(
        "# Changelog: kit-alpha\n\n"
        "## v2.0.0 — Major refactor\n\n"
        "- Replaced the authentication flow (breaking).\n\n"
        "## v1.0.0 — Initial\n\n- Initial release.\n",
        encoding="utf-8",
    )


def _alpha(out: dict) -> dict:
    return next(k for k in out["kits"] if k["name"] == "kit-alpha")


def test_unpinned_multi_version_serves_earliest_with_advisory(
    kit_root: Path,
) -> None:
    _add_kit_alpha_v2(kit_root)
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    alpha = _alpha(out)
    assert alpha["version"] == "v1"
    assert "v2" in alpha["always_load_markdown"] or "layered" in (
        alpha["always_load_markdown"]
    )
    advisory = alpha["version_advisory"]
    assert advisory["reason"] == "unpinned-multi-version"
    assert advisory["latest_version"] == "v2"
    assert [c["version"] for c in advisory["breaking_changes"]] == ["v2.0.0"]
    assert advisory["user_facing_warning"] is True


def test_pin_selects_that_version_without_advisory(kit_root: Path) -> None:
    _add_kit_alpha_v2(kit_root)
    out = resolver.resolve_kits(
        task="add a FastAPI REST endpoint",
        pins={"kit-alpha": "v2"},
    )
    alpha = _alpha(out)
    assert alpha["version"] == "v2"
    assert "version_advisory" not in alpha
    # v2's always-load content is what gets inlined.
    assert "v2" in alpha["always_load_markdown"]


def test_single_version_kit_has_no_advisory(kit_root: Path) -> None:
    # kit-alpha is single-version in the base fixture.
    out = resolver.resolve_kits(task="add a FastAPI REST endpoint")
    alpha = _alpha(out)
    assert alpha["version"] == "v1"
    assert "version_advisory" not in alpha
