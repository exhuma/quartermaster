"""Tests for the derived, capped per-user memory store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.observability.local_store import LocalMetricsStore
from app.storage import user_memory


@pytest.fixture()
def store(tmp_path: Path) -> LocalMetricsStore:
    s = LocalMetricsStore(tmp_path / "metrics.db", retention_days=30)
    s.init()
    return s


@pytest.fixture(autouse=True)
def _fake_kit_domains(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deterministic kit->domain mapping, independent of any real catalog.
    monkeypatch.setattr(
        "app.storage.user_memory.kit_domain_map",
        lambda: {
            "module-auth-oidc": ["auth"],
            "module-fastapi": ["rest-api", "backend"],
            "module-docs": ["docs"],
        },
    )


def _seed(
    store: LocalMetricsStore,
    *,
    subject: str,
    kit: str,
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    ts: float | None = None,
) -> None:
    store.record_resolve(
        engine="lexical",
        confidence="high",
        coverage=0.75,
        broadening=False,
        deliveries=[(kit, "inlined", 100)],
        delivered_tokens=100,
        offered_tokens=0,
        subject=subject,
        traits_json=json.dumps(
            {"languages": languages or [], "frameworks": frameworks or []}
        ),
    )
    if ts is not None:
        store._conn.execute(
            "UPDATE resolve_events SET ts = ? WHERE subject = ? "
            "AND ts = (SELECT MAX(ts) FROM resolve_events WHERE subject = ?)",
            (ts, subject, subject),
        )
        store._conn.commit()


def test_derive_profile_ranks_by_frequency_and_caps(
    store: LocalMetricsStore,
) -> None:
    now = 1_000_000.0
    for _ in range(3):
        _seed(
            store,
            subject="alice",
            kit="module-auth-oidc",
            languages=["python"],
            ts=now,
        )
    _seed(
        store, subject="alice", kit="module-docs", languages=["python"], ts=now
    )

    profile = user_memory.derive_profile(
        store,
        "alice",
        now=now,
        half_life_days=30,
        caps=user_memory.ProfileCaps(
            domains=5, kits=1, languages=3, frameworks=3
        ),
    )
    # capped to 1, most frequent
    assert profile["top_kits"] == ["module-auth-oidc"]
    assert "auth" in profile["top_domains"]
    assert profile["top_languages"] == ["python"]


def test_derive_profile_decay_recent_beats_old(
    store: LocalMetricsStore,
) -> None:
    now = 1_000_000.0
    old_ts = now - 200 * 86_400  # far older than the half-life
    _seed(store, subject="alice", kit="module-docs", ts=old_ts)
    _seed(store, subject="alice", kit="module-fastapi", ts=now)

    profile = user_memory.derive_profile(
        store,
        "alice",
        now=now,
        half_life_days=30,
        caps=user_memory.ProfileCaps(
            domains=5, kits=1, languages=3, frameworks=3
        ),
    )
    assert profile["top_kits"] == ["module-fastapi"]


def test_derive_profile_isolates_subjects(store: LocalMetricsStore) -> None:
    now = 1_000_000.0
    _seed(store, subject="alice", kit="module-auth-oidc", ts=now)
    _seed(store, subject="bob", kit="module-fastapi", ts=now)

    alice_profile = user_memory.derive_profile(
        store,
        "alice",
        now=now,
        half_life_days=30,
        caps=user_memory.ProfileCaps(),
    )
    assert "module-fastapi" not in alice_profile["top_kits"]
    assert "module-auth-oidc" in alice_profile["top_kits"]


def test_derive_profile_empty_for_unknown_subject(
    store: LocalMetricsStore,
) -> None:
    profile = user_memory.derive_profile(
        store, "nobody", now=1_000_000.0, half_life_days=30,
        caps=user_memory.ProfileCaps(),
    )
    assert profile["top_kits"] == []
    assert profile["top_domains"] == []
    assert profile["top_languages"] == []
    assert profile["top_frameworks"] == []
    assert profile["updated"]


def test_save_load_clear_profile_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "user-memory.toml"
    assert user_memory.load_profile(path, "alice") is None

    profile = {
        "updated": "2026-01-01T00:00:00+00:00",
        "top_domains": ["auth"],
        "top_kits": ["module-auth-oidc"],
        "top_languages": ["python"],
        "top_frameworks": [],
    }
    user_memory.save_profile(path, "alice", profile)
    assert user_memory.load_profile(path, "alice") == profile

    assert user_memory.clear_profile(path, "alice") is True
    assert user_memory.load_profile(path, "alice") is None
    assert user_memory.clear_profile(path, "alice") is False  # idempotent


def test_get_or_build_returns_cached_profile_when_fresh(
    store: LocalMetricsStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "user-memory.toml"
    cached = {
        "updated": "2026-07-02T12:00:00+00:00",
        "top_domains": [],
        "top_kits": ["cached-kit"],
        "top_languages": [],
        "top_frameworks": [],
    }
    user_memory.save_profile(path, "alice", cached)

    def _boom(*args, **kwargs):
        raise AssertionError("derive_profile must not run when cache is fresh")

    monkeypatch.setattr(user_memory, "derive_profile", _boom)

    now = user_memory._parse_iso(cached["updated"]) + 10  # well within TTL
    result = user_memory.get_or_build(
        path, "alice", store, ttl_seconds=3600, half_life_days=30,
        caps=user_memory.ProfileCaps(), now=now,
    )
    assert result == cached


def test_get_or_build_rebuilds_when_stale(
    store: LocalMetricsStore, tmp_path: Path
) -> None:
    path = tmp_path / "user-memory.toml"
    stale_ts = "2020-01-01T00:00:00+00:00"
    user_memory.save_profile(
        path,
        "alice",
        {
            "updated": stale_ts,
            "top_domains": [],
            "top_kits": ["old-kit"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    now = user_memory._parse_iso(stale_ts) + 999_999
    _seed(store, subject="alice", kit="module-fastapi", ts=now)

    result = user_memory.get_or_build(
        path, "alice", store, ttl_seconds=3600, half_life_days=30,
        caps=user_memory.ProfileCaps(), now=now,
    )
    assert result["top_kits"] == ["module-fastapi"]
    # rebuilt + persisted
    assert user_memory.load_profile(path, "alice") == result


def test_get_or_build_rebuilds_when_missing(
    store: LocalMetricsStore, tmp_path: Path
) -> None:
    path = tmp_path / "user-memory.toml"
    now = 1_000_000.0
    _seed(store, subject="alice", kit="module-docs", ts=now)

    result = user_memory.get_or_build(
        path, "alice", store, ttl_seconds=3600, half_life_days=30,
        caps=user_memory.ProfileCaps(), now=now,
    )
    assert result["top_kits"] == ["module-docs"]


def test_get_or_build_never_raises_on_derive_failure(
    store: LocalMetricsStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "user-memory.toml"

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(user_memory, "derive_profile", _boom)
    result = user_memory.get_or_build(
        path, "alice", store, ttl_seconds=3600, half_life_days=30,
        caps=user_memory.ProfileCaps(), now=1_000_000.0,
    )
    assert result["top_kits"] == []


def test_empty_profile_has_no_timestamp() -> None:
    profile = user_memory.empty_profile()
    assert profile["updated"] is None
    assert profile["top_domains"] == []
    assert profile["top_kits"] == []
    assert profile["top_languages"] == []
    assert profile["top_frameworks"] == []
