"""
Tests for the pure eval scoring layer (``app.eval.report``).

These use synthetic resolution records — no catalog, resolver, or model — so
they pin the verdict logic, false-exclusion computation, and aggregate report
shape deterministically.
"""

from __future__ import annotations

from typing import Any

from app.eval.report import (
    build_report,
    false_exclusions,
    verdict_for,
)

# A tiny catalog: one kit that excludes js/ts.
_CATALOG = [
    {"name": "mod-py", "excludes": {}},
    {
        "name": "mod-style",
        "excludes": {"languages": ["javascript", "typescript"]},
    },
]


def _record(**over: Any) -> dict[str, Any]:
    base = {
        "id": "curated::case",
        "source": "curated",
        "engine": "embedding",
        "task": "do a python thing",
        "inferred_traits": {
            "languages": ["python"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        "kits": [{"name": "mod-py", "score": 100}],
        "expect": {
            "include": {"languages": ["python"]},
            "forbid": {"languages": ["javascript", "typescript"]},
            "kits_include": ["mod-py"],
            "kits_forbid": [],
        },
    }
    base.update(over)
    return base


def test_clean_record_passes() -> None:
    assert verdict_for(_record()) == []


def test_contamination_detected() -> None:
    rec = _record(
        inferred_traits={
            "languages": ["python", "javascript"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        }
    )
    findings = verdict_for(rec)
    kinds = {f["kind"] for f in findings}
    assert "contamination" in kinds
    contam = next(f for f in findings if f["kind"] == "contamination")
    assert contam["traits"] == ["javascript"]


def test_missing_and_recall_and_engine_drift() -> None:
    rec = _record(
        engine="lexical",
        inferred_traits={
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        kits=[],
    )
    kinds = {f["kind"] for f in verdict_for(rec)}
    assert {"recall-miss", "missing-kit", "engine-drift"} <= kinds


def test_false_exclusion_confirmed_vs_incidental() -> None:
    from app.eval.report import _excludes_by_kit

    excludes_by_kit = _excludes_by_kit(_CATALOG)
    # js is both inferred AND labelled forbidden -> confirmed spurious.
    rec = _record(
        inferred_traits={
            "languages": ["python", "javascript"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        }
    )
    fx = false_exclusions(rec, excludes_by_kit)
    assert len(fx) == 1
    assert fx[0]["kit"] == "mod-style"
    assert fx[0]["confirmed_spurious"] is True

    # A record with no forbid label -> exclusion still found, not "confirmed".
    rec2 = _record(
        expect={
            "include": {},
            "forbid": {},
            "kits_include": [],
            "kits_forbid": [],
        },
        inferred_traits={
            "languages": ["typescript"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
    )
    fx2 = false_exclusions(rec2, excludes_by_kit)
    assert fx2[0]["confirmed_spurious"] is False


def test_build_report_aggregates() -> None:
    clean = _record(id="curated::ok")
    dirty = _record(
        id="curated::leak",
        inferred_traits={
            "languages": ["python", "javascript"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
    )
    report = build_report([clean, dirty], _CATALOG)
    assert report["totals"] == {"cases": 2, "passed": 1, "failed": 1}
    # mod-style excluded once (by the leaking case), confirmed spurious.
    tally = report["false_exclusion_tally"]["mod-style"]
    assert tally["count"] == 1
    assert tally["confirmed_spurious"] == 1
    # both cases forbid js -> js leaked in 1 of 2 (nested by category).
    assert report["contamination"]["languages"]["javascript"] == {
        "forbidden": 2,
        "leaked": 1,
    }


def _catalog_probe(kit: str, ranked: list[str]) -> dict[str, Any]:
    """A catalog self-probe record where `ranked` is the resolved kit order."""
    return {
        "id": f"catalog::{kit}",
        "source": "catalog",
        "engine": "embedding",
        "task": f"work on {kit}",
        "inferred_traits": {
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        "kits": [{"name": n, "score": 100 - i} for i, n in enumerate(ranked)],
        "expect": {
            "include": {},
            "forbid": {},
            "kits_include": [kit],
            "kits_forbid": [],
        },
    }


def test_interference_attribution() -> None:
    # kit-b's own probe is topped by kit-a -> kit-a displaces kit-b.
    rec = _catalog_probe("kit-b", ["kit-a", "kit-b"])
    report = build_report([rec], catalog=[])
    case = report["cases"][0]
    assert case["self_rank"] == 1
    assert case["displaced_by"] == ["kit-a"]
    assert report["interference_tally"]["kit-a"]["displaces"] == {"kit-b": 1}
    # a kit that tops its own probe records no interference.
    clean = build_report([_catalog_probe("kit-a", ["kit-a", "kit-b"])], [])
    assert clean["interference_tally"] == {}
    assert clean["cases"][0]["displaced_by"] == []


def test_diff_reports_surfaces_regression() -> None:
    from app.eval.report import diff_reports

    baseline = build_report([_catalog_probe("kit-b", ["kit-b"])], [])
    # candidate: kit-b no longer resolves to itself (only kit-a returned).
    candidate = build_report([_catalog_probe("kit-b", ["kit-a"])], [])
    diff = diff_reports(baseline, candidate)
    assert "catalog::kit-b" in diff["newly_failing"]
    assert "kit-b" in diff["kits"]["newly_missing"]
    assert diff["newly_passing"] == []


def test_build_report_flags_nondeterminism() -> None:
    a = _record(id="curated::x")
    b = _record(
        id="curated::x",
        inferred_traits={
            "languages": ["python", "go"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
    )
    report = build_report([a, b], _CATALOG)
    assert "curated::x" in report["nondeterministic"]
