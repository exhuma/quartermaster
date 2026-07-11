"""Tests for agent-in-the-loop clarification detection (app.clarify)."""

from __future__ import annotations

from types import SimpleNamespace

from app import clarify
from app.traits import TraitVocabulary


def _vocab() -> TraitVocabulary:
    return TraitVocabulary(
        languages=["csharp", "go", "python", "typescript"],
        frameworks=["django", "fastapi"],
        capabilities=["database"],
        contexts=["backend"],
    )


def _settings(
    *,
    enabled: bool = True,
    max_questions: int = 2,
    min_blocking: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        clarification_enabled=enabled,
        clarification_max_questions=max_questions,
        clarification_min_blocking_kits=min_blocking,
    )


def _inferred(**overrides: list[str]) -> dict[str, list[str]]:
    base = {
        "languages": [],
        "frameworks": [],
        "capabilities": ["database"],
        "contexts": [],
    }
    base.update(overrides)
    return base


def _candidate(name: str, reasons: list[str], needs: dict) -> dict:
    return {"name": name, "reasons": reasons, "needs": needs}


def _lang_blocking(name: str = "db-kit") -> dict:
    return _candidate(name, ["need-trait:languages"], {"languages": ["python"]})


def _selection(candidates: list[dict], confidence: str = "medium") -> dict:
    return {"candidates": candidates, "confidence": confidence}


def _detect(selection: dict, inferred: dict, **settings_kw):
    return clarify.detect_clarification(
        selection=selection,
        inferred=inferred,
        vocab=_vocab(),
        settings=_settings(**settings_kw),
    )


def test_fires_even_at_high_confidence() -> None:
    # "add a database" fully covers its one inferred dimension -> "high"
    # aggregate confidence, yet a missing required language must still clarify.
    # The need-trait signal is not masked by the confidence string.
    selection = _selection([_lang_blocking()], confidence="high")
    signal = _detect(selection, _inferred())
    assert signal is not None
    assert signal.questions[0].category == "languages"


def test_none_when_dimension_already_inferred() -> None:
    # A kit needs languages, but the task already provided one — the
    # loop-breaker: never re-ask about an inferred dimension.
    selection = _selection(
        [
            _candidate(
                "db-kit",
                ["need-trait:languages"],
                {"languages": ["python", "csharp"]},
            )
        ]
    )
    assert _detect(selection, _inferred(languages=["python"])) is None


def test_languages_question_with_narrowed_options() -> None:
    selection = _selection(
        [
            _candidate(
                "db-postgres",
                ["match:capabilities", "need-trait:languages"],
                {"languages": ["python"]},
            ),
            _candidate(
                "db-efcore",
                ["match:capabilities", "need-trait:languages"],
                {"languages": ["csharp"]},
            ),
        ]
    )
    signal = _detect(selection, _inferred())
    assert signal is not None
    assert signal.reason == "pivotal-trait-missing"
    assert len(signal.questions) == 1
    question = signal.questions[0]
    assert question.category == "languages"
    # Options narrowed to exactly the values the blocking kits require.
    assert question.options == ["csharp", "python"]
    assert sorted(question.blocking_kits) == ["db-efcore", "db-postgres"]


def test_options_fall_back_to_full_vocab_when_needs_empty() -> None:
    selection = _selection([_candidate("db-kit", ["need-trait:languages"], {})])
    signal = _detect(selection, _inferred())
    assert signal is not None
    assert signal.questions[0].options == [
        "csharp",
        "go",
        "python",
        "typescript",
    ]


def test_cap_and_priority_order() -> None:
    # Two missing dimensions (languages + contexts); languages must come first
    # (higher selector weight) and the cap of 1 keeps only it.
    selection = _selection(
        [
            _candidate(
                "kit",
                ["need-trait:contexts", "need-trait:languages"],
                {"languages": ["python"], "contexts": ["backend"]},
            )
        ]
    )
    signal = _detect(selection, _inferred(), max_questions=1)
    assert signal is not None
    assert [q.category for q in signal.questions] == ["languages"]


def test_min_blocking_kits_threshold() -> None:
    selection = _selection([_lang_blocking()])
    assert _detect(selection, _inferred(), min_blocking=2) is None


def test_none_when_disabled() -> None:
    selection = _selection([_lang_blocking()])
    assert _detect(selection, _inferred(), enabled=False) is None


def test_none_when_no_candidates() -> None:
    assert _detect(_selection([]), _inferred()) is None
