"""
Tests for the always-on local metrics store (``app.observability.local_store``).

These exercise the SQLite event store directly against a ``tmp_path`` database:
schema init, record→aggregate roundtrips, rolling-window pruning, behavioural
co-occurrence, and the static structural-overlap (trait Jaccard) computation.
The store is deliberately OTEL-independent, so nothing here touches telemetry.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.kits import KitApplicability, KitInfo
from app.observability import local_store as ls


@pytest.fixture()
def store(tmp_path: Path) -> ls.LocalMetricsStore:
    s = ls.LocalMetricsStore(tmp_path / "metrics.db", retention_days=7)
    s.init()
    return s


def _applicability(**overrides) -> KitApplicability:
    base = dict(
        kit_type="module",
        summary="s",
        domains=["testing"],
        languages=["python"],
        frameworks=[],
        contexts=["backend"],
        requires={
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        excludes={
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        optional_signals=[],
        related_kits=[],
        priority=50,
    )
    base.update(overrides)
    return KitApplicability(**base)


def test_init_is_idempotent_and_creates_schema(tmp_path: Path) -> None:
    s = ls.LocalMetricsStore(tmp_path / "m.db", retention_days=7)
    s.init()
    s.init()  # second call must not raise
    # An empty store aggregates cleanly.
    assert s.kit_usage(0.0) == []
    assert s.tokens_timeseries(0.0) == []
    assert s.resolve_health(0.0)["total_calls"] == 0


def test_kit_usage_counts_delivered_not_offered(
    store: ls.LocalMetricsStore,
) -> None:
    store.record_resolve(
        engine="lexical",
        confidence="high",
        coverage=0.75,
        broadening=False,
        deliveries=[("kit-a", "inlined", 100), ("kit-b", "offered", 40)],
        delivered_tokens=100,
        offered_tokens=40,
    )
    store.record_delivery(kit="kit-a", disposition="full", tokens=200)

    usage = {r["kit"]: r for r in store.kit_usage(0.0)}
    # kit-a delivered twice (inlined + full); kit-b was only offered → absent.
    assert usage["kit-a"]["deliveries"] == 2
    assert usage["kit-a"]["tokens"] == 300
    assert "kit-b" not in usage


def test_tokens_timeseries_splits_delivered_and_offered(
    store: ls.LocalMetricsStore,
) -> None:
    store.record_resolve(
        engine="lexical",
        confidence="low",
        coverage=0.2,
        broadening=True,
        deliveries=[("kit-a", "inlined", 100), ("kit-a", "offered", 25)],
        delivered_tokens=100,
        offered_tokens=25,
    )
    series = store.tokens_timeseries(0.0)
    assert len(series) == 1
    assert series[0]["delivered"] == 100
    assert series[0]["offered"] == 25


def test_tokens_timeseries_hourly_vs_daily_buckets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1_000_000.0}  # 1970-01-12 13:46:40 UTC
    monkeypatch.setattr(ls.time, "time", lambda: clock["now"])
    s = ls.LocalMetricsStore(tmp_path / "m.db", retention_days=7)
    s.init()

    # Two deliveries an hour apart on the same UTC day.
    s.record_delivery(kit="kit-a", disposition="full", tokens=10)
    clock["now"] += 3600
    s.record_delivery(kit="kit-a", disposition="full", tokens=20)

    hourly = s.tokens_timeseries(0.0, "1h")
    assert len(hourly) == 2  # two distinct hour buckets
    assert sum(p["delivered"] for p in hourly) == 30

    daily = s.tokens_timeseries(0.0, "1d")  # default granularity
    assert len(daily) == 1  # collapsed to one day bucket
    assert daily[0]["delivered"] == 30


def test_catalog_growth_hourly_forward_fills_daily_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(ls.time, "time", lambda: clock["now"])
    s = ls.LocalMetricsStore(tmp_path / "m.db", retention_days=7)
    s.init()

    day = ls.time.strftime("%Y-%m-%d", ls.time.gmtime(clock["now"]))
    with s._lock:
        s._conn.execute("DELETE FROM catalog_snapshots")
        s._conn.execute(
            "INSERT INTO catalog_snapshots "
            "(day, domain, kits, sections, total_tokens, always_load_tokens) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (day, "testing", 1, 1, 500, 100),
        )
        s._conn.commit()

    g = s.catalog_growth(0.0, "1h")
    # The single daily snapshot is forward-filled across hourly buckets, each
    # holding the day's value and labelled with an hourly ("day HH:00") bucket.
    assert g["catalog"]
    assert all(p["day"].startswith(day + " ") for p in g["catalog"])
    assert all(p["total_tokens"] == 500 for p in g["catalog"])


def test_resolve_health_mixes_and_broadening_rate(
    store: ls.LocalMetricsStore,
) -> None:
    for conf, broad in [("high", False), ("low", True)]:
        store.record_resolve(
            engine="embedding",
            confidence=conf,
            coverage=0.5,
            broadening=broad,
            deliveries=[("kit-a", "inlined", 10)],
            delivered_tokens=10,
            offered_tokens=0,
        )
    health = store.resolve_health(0.0)
    assert health["total_calls"] == 2
    assert health["engine_mix"] == {"embedding": 2}
    assert health["confidence_mix"] == {"high": 1, "low": 1}
    assert health["broadening_rate"] == 0.5


def test_tool_latency_percentiles_and_errors(
    store: ls.LocalMetricsStore,
) -> None:
    for d, ok in [(10.0, True), (20.0, True), (30.0, False)]:
        store.record_tool_call(tool="get_kit", ok=ok, duration_ms=d)
    rows = {r["tool"]: r for r in store.tool_latency(0.0)}
    assert rows["get_kit"]["calls"] == 3
    assert rows["get_kit"]["errors"] == 1
    assert rows["get_kit"]["p50_ms"] == 20.0


def test_co_occurrence_jaccard(store: ls.LocalMetricsStore) -> None:
    store.record_resolve(
        engine="lexical", confidence="high", coverage=1.0, broadening=False,
        deliveries=[("kit-a", "inlined", 1), ("kit-b", "inlined", 1)],
        delivered_tokens=2, offered_tokens=0,
    )
    store.record_resolve(
        engine="lexical", confidence="high", coverage=1.0, broadening=False,
        deliveries=[("kit-a", "inlined", 1), ("kit-c", "inlined", 1)],
        delivered_tokens=2, offered_tokens=0,
    )
    result = store.co_occurrence(0.0)
    assert result["kits"] == ["kit-a", "kit-b", "kit-c"]
    idx = {k: i for i, k in enumerate(result["kits"])}
    # kit-a appears in 2 resolves, kit-b in 1, together once → 1/(2+1-1)=0.5
    ab = [
        c for c in result["cells"]
        if c["x"] == idx["kit-a"] and c["y"] == idx["kit-b"]
    ]
    assert ab and ab[0]["value"] == pytest.approx(0.5)
    assert ab[0]["count"] == 1


def test_rolling_window_prunes_old_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = {"now": 1_000_000.0}
    monkeypatch.setattr(ls.time, "time", lambda: clock["now"])
    s = ls.LocalMetricsStore(tmp_path / "m.db", retention_days=1)
    s.init()

    # An old delivery, well outside the 1-day window.
    s.record_delivery(kit="old", disposition="full", tokens=1)
    clock["now"] += 2 * 86_400  # advance two days
    s.record_delivery(kit="new", disposition="full", tokens=1)

    s._prune_locked()
    kits = {r["kit"] for r in s.kit_usage(0.0)}
    assert kits == {"new"}


def test_structural_overlap_jaccard(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = [
        (KitInfo("kit-a", "d", ["v1"], "v1"),
         _applicability(languages=["python"], frameworks=["fastapi"])),
        (KitInfo("kit-b", "d", ["v1"], "v1"),
         _applicability(languages=["python"], frameworks=["django"])),
    ]
    monkeypatch.setattr("app.kits.iter_catalog", lambda: catalog)
    result = ls.structural_overlap()
    assert result["kits"] == ["kit-a", "kit-b"]
    # Shared traits: lang:python + dom:testing + ctx:backend = 3.
    # Union adds fw:fastapi and fw:django = 5 total → 3/5 = 0.6.
    cell = next(c for c in result["cells"] if c["x"] == 0 and c["y"] == 1)
    assert cell["value"] == pytest.approx(0.6)


def test_record_resolve_persists_subject_and_traits(
    store: ls.LocalMetricsStore,
) -> None:
    store.record_resolve(
        engine="lexical",
        confidence="high",
        coverage=0.75,
        broadening=False,
        deliveries=[],
        delivered_tokens=0,
        offered_tokens=0,
        subject="alice",
        traits_json='{"languages": ["python"]}',
    )
    row = store._conn.execute(
        "SELECT subject, traits_json FROM resolve_events"
    ).fetchone()
    assert row["subject"] == "alice"
    assert row["traits_json"] == '{"languages": ["python"]}'


def test_record_resolve_subject_defaults_to_null(
    store: ls.LocalMetricsStore,
) -> None:
    store.record_resolve(
        engine="lexical",
        confidence="high",
        coverage=0.75,
        broadening=False,
        deliveries=[],
        delivered_tokens=0,
        offered_tokens=0,
    )
    row = store._conn.execute(
        "SELECT subject, traits_json FROM resolve_events"
    ).fetchone()
    assert row["subject"] is None
    assert row["traits_json"] is None


def test_init_migrates_pre_existing_db_missing_subject_columns(
    tmp_path: Path,
) -> None:
    import sqlite3

    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE resolve_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            engine TEXT,
            confidence TEXT,
            coverage REAL,
            broadening INTEGER NOT NULL DEFAULT 0,
            delivered_tokens INTEGER NOT NULL DEFAULT 0,
            offered_tokens INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    import time as _time

    conn.execute(
        "INSERT INTO resolve_events "
        "(ts, engine, confidence, coverage, broadening, delivered_tokens, "
        " offered_tokens) VALUES (?, 'lexical', 'high', 0.5, 0, 10, 5)",
        (_time.time(),),
    )
    conn.commit()
    conn.close()

    s = ls.LocalMetricsStore(db_path, retention_days=7)
    s.init()

    cols = {
        r["name"]
        for r in s._conn.execute("PRAGMA table_info(resolve_events)")
    }
    assert "subject" in cols
    assert "traits_json" in cols

    row = s._conn.execute(
        "SELECT subject, traits_json, engine FROM resolve_events"
    ).fetchone()
    assert row["subject"] is None
    assert row["traits_json"] is None
    assert row["engine"] == "lexical"


def test_resolve_history_for_subject_includes_delivered_kits_and_traits(
    store: ls.LocalMetricsStore,
) -> None:
    store.record_resolve(
        engine="lexical",
        confidence="high",
        coverage=0.75,
        broadening=False,
        deliveries=[("kit-a", "inlined", 100), ("kit-b", "offered", 40)],
        delivered_tokens=100,
        offered_tokens=40,
        subject="alice",
        traits_json='{"languages": ["python"], "frameworks": ["fastapi"]}',
    )
    # A different subject's resolve must never leak into alice's history.
    store.record_resolve(
        engine="lexical",
        confidence="high",
        coverage=0.75,
        broadening=False,
        deliveries=[("kit-c", "inlined", 10)],
        delivered_tokens=10,
        offered_tokens=0,
        subject="bob",
        traits_json="{}",
    )

    history = store.resolve_history_for_subject("alice", 0.0)
    assert len(history) == 1
    event = history[0]
    assert event["kits"] == ["kit-a"]  # only the delivered (not offered) kit
    assert '"python"' in event["traits_json"]


def test_resolve_history_for_subject_empty_for_unknown_subject(
    store: ls.LocalMetricsStore,
) -> None:
    assert store.resolve_history_for_subject("nobody", 0.0) == []
