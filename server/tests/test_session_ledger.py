"""
Tests for the in-memory session delivery ledger (app/session_ledger.py).

Cover the dedup contract (record then filter), version keying, TTL expiry,
LRU capacity eviction, never-raise behaviour, and the settings-gated singleton.
"""

from __future__ import annotations

import threading

from app import session_ledger
from app.session_ledger import SessionDeliveryLedger


def test_records_then_filters_as_already_delivered() -> None:
    ledger = SessionDeliveryLedger()
    ledger.record_delivered("s", "kit", "v1", ["a", "b"], now=1000.0)
    fresh, already = ledger.filter_already_delivered(
        "s", "kit", "v1", ["a", "b", "c"], now=1001.0
    )
    assert fresh == ["c"]
    assert sorted(already) == ["a", "b"]


def test_unknown_session_is_all_fresh() -> None:
    ledger = SessionDeliveryLedger()
    fresh, already = ledger.filter_already_delivered(
        "never-seen", "kit", "v1", ["a"], now=1.0
    )
    assert fresh == ["a"]
    assert already == []


def test_no_session_id_is_all_fresh() -> None:
    ledger = SessionDeliveryLedger()
    ledger.record_delivered(None, "kit", "v1", ["a"], now=1.0)
    fresh, already = ledger.filter_already_delivered(
        None, "kit", "v1", ["a"], now=2.0
    )
    assert fresh == ["a"]
    assert already == []


def test_keyed_on_kit_and_version() -> None:
    ledger = SessionDeliveryLedger()
    ledger.record_delivered("s", "kit", "v1", ["a"], now=1.0)
    # Same id, different major -> still fresh (distinct ledger key).
    fresh_v2, already_v2 = ledger.filter_already_delivered(
        "s", "kit", "v2", ["a"], now=2.0
    )
    assert fresh_v2 == ["a"]
    assert already_v2 == []
    # Same id, different kit -> still fresh.
    fresh_other, _ = ledger.filter_already_delivered(
        "s", "other", "v1", ["a"], now=2.0
    )
    assert fresh_other == ["a"]


def test_ttl_expiry_forgets_stale_sessions() -> None:
    ledger = SessionDeliveryLedger(ttl_seconds=100)
    ledger.record_delivered("s", "kit", "v1", ["a"], now=1000.0)
    # Well past the TTL -> the session is forgotten -> all fresh again.
    fresh, already = ledger.filter_already_delivered(
        "s", "kit", "v1", ["a"], now=1000.0 + 101
    )
    assert fresh == ["a"]
    assert already == []


def test_lru_capacity_eviction() -> None:
    ledger = SessionDeliveryLedger(max_sessions=1)
    ledger.record_delivered("s1", "kit", "v1", ["a"], now=1.0)
    # Recording a second session evicts the least-recently-used (s1).
    ledger.record_delivered("s2", "kit", "v1", ["a"], now=2.0)
    fresh_s1, _ = ledger.filter_already_delivered(
        "s1", "kit", "v1", ["a"], now=3.0
    )
    assert fresh_s1 == ["a"]
    # s2 (the survivor) is still remembered.
    _, already_s2 = ledger.filter_already_delivered(
        "s2", "kit", "v1", ["a"], now=3.0
    )
    assert already_s2 == ["a"]


def test_empty_section_ids_are_noops() -> None:
    ledger = SessionDeliveryLedger()
    ledger.record_delivered("s", "kit", "v1", [], now=1.0)
    fresh, already = ledger.filter_already_delivered(
        "s", "kit", "v1", [], now=2.0
    )
    assert fresh == []
    assert already == []


def test_concurrent_record_is_thread_safe() -> None:
    ledger = SessionDeliveryLedger()

    def _worker(i: int) -> None:
        ledger.record_delivered("s", "kit", "v1", [f"sec-{i}"], now=1.0)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    ids = [f"sec-{i}" for i in range(50)]
    _, already = ledger.filter_already_delivered(
        "s", "kit", "v1", ids, now=2.0
    )
    assert sorted(already) == sorted(ids)


def test_get_ledger_respects_enabled_flag() -> None:
    session_ledger.reset_for_tests()
    disabled = type("S", (), {"resolve_dedup_enabled": False})()
    assert session_ledger.get_ledger(disabled) is None

    session_ledger.reset_for_tests()
    enabled = type(
        "S",
        (),
        {
            "resolve_dedup_enabled": True,
            "resolve_dedup_ttl_seconds": 60,
            "resolve_dedup_max_sessions": 10,
        },
    )()
    ledger = session_ledger.get_ledger(enabled)
    assert isinstance(ledger, SessionDeliveryLedger)
    # Singleton: a second call returns the same instance.
    assert session_ledger.get_ledger(enabled) is ledger
    session_ledger.reset_for_tests()
