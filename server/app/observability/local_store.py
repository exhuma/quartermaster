"""
Always-on local metrics store (SQLite), independent of OpenTelemetry.

The store records three event streams — resolve calls, kit deliveries, and MCP
tool calls — plus a daily catalog snapshot, into a single SQLite database on a
mounted volume (so it survives container restarts). It keeps only a rolling
window (``retention_days``) to bound storage; long-term history is OTEL's job.

Design rules, mirroring :mod:`app.telemetry`:

* **Best-effort.** Every write is wrapped so a storage failure never raises
  into the request/tool path.
* **OTEL-independent.** Recording is *not* gated on ``telemetry._initialized``;
  it runs whether or not an OTLP endpoint is configured.
* **Event rows, not counters.** Deliveries carry a nullable ``resolve_id`` so
  the "which kits were delivered together" set survives — that grouping is lost
  in the OTEL counters and is what powers the behavioural distinctness view.

Read/aggregate helpers (used by ``app.routers.metrics``) do all grouping in SQL
where possible; percentiles are computed in Python since SQLite has none.
"""

from __future__ import annotations

import logging
import math
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.observability")

# Prune at most once every this-many writes (plus once on init), so a hot path
# never pays for a DELETE on every event.
_PRUNE_EVERY = 200

# Dispositions that represent content actually sent to the client (as opposed
# to ``offered`` for later on-demand fetch). Used for "usage" and "delivered
# tokens" so an offered-but-never-fetched kit does not read as used.
_DELIVERED = ("inlined", "full", "sections")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS resolve_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    engine TEXT,
    confidence TEXT,
    coverage REAL,
    broadening INTEGER NOT NULL DEFAULT 0,
    delivered_tokens INTEGER NOT NULL DEFAULT 0,
    offered_tokens INTEGER NOT NULL DEFAULT 0,
    suppressed_tokens INTEGER NOT NULL DEFAULT 0,
    subject TEXT,
    traits_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_resolve_ts ON resolve_events (ts);

CREATE TABLE IF NOT EXISTS deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    kit TEXT NOT NULL,
    disposition TEXT NOT NULL,
    tokens INTEGER NOT NULL DEFAULT 0,
    resolve_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_deliveries_ts ON deliveries (ts);
CREATE INDEX IF NOT EXISTS ix_deliveries_resolve ON deliveries (resolve_id);

CREATE TABLE IF NOT EXISTS tool_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    tool TEXT NOT NULL,
    ok INTEGER NOT NULL,
    duration_ms REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tool_ts ON tool_calls (ts);

CREATE TABLE IF NOT EXISTS catalog_snapshots (
    day TEXT NOT NULL,
    domain TEXT NOT NULL,
    kits INTEGER NOT NULL DEFAULT 0,
    sections INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    always_load_tokens INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, domain)
);

CREATE TABLE IF NOT EXISTS kit_version_uses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    subject TEXT,
    project_id TEXT,
    kit TEXT NOT NULL,
    version TEXT NOT NULL,
    pinned INTEGER NOT NULL DEFAULT 0,
    advisory_shown INTEGER NOT NULL DEFAULT 0,
    resolve_id INTEGER
);
CREATE INDEX IF NOT EXISTS ix_kit_version_uses_ts
    ON kit_version_uses (ts);
CREATE INDEX IF NOT EXISTS ix_kit_version_uses_kit
    ON kit_version_uses (kit, ts);
"""


def _version_sort_key(v: str) -> tuple[int, str]:
    """Sort ``v<N>`` labels numerically, unknown shapes last by label."""
    m = re.fullmatch(r"v(\d+)", v or "")
    return (int(m.group(1)), "") if m else (10**9, v or "")


def _percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile (``q`` in ``[0, 1]``); 0.0 if empty."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * q
    low = math.floor(k)
    high = math.ceil(k)
    if low == high:
        return float(ordered[int(k)])
    return float(ordered[low] * (high - k) + ordered[high] * (k - low))


class LocalMetricsStore:
    """A thread-safe SQLite-backed rolling-window metrics store.

    A single connection is shared behind a lock (``check_same_thread=False``);
    events are tiny and infrequent, so a global lock is simpler than a pool and
    keeps writes atomic. WAL mode lets the read API run concurrently with
    writes.
    """

    def __init__(
        self,
        db_path: Path,
        retention_days: int,
        version_telemetry_enabled: bool = True,
    ) -> None:
        self._path = Path(db_path)
        self._retention_seconds = max(1, int(retention_days)) * 86_400
        self._version_telemetry_enabled = bool(version_telemetry_enabled)
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._writes = 0

    # -- lifecycle ---------------------------------------------------------

    def init(self) -> None:
        """Open the DB, create the schema, prune once, snapshot the catalog."""
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._path), check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._migrate_locked()
            self._conn.commit()
            self._prune_locked()
        # Snapshot outside the lock (it reads the catalog, which can be slow)
        # but is itself best-effort and takes the lock only to write.
        self.maybe_snapshot_catalog()

    def close(self) -> None:
        """Close the underlying connection (used in tests and shutdown)."""
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- write path (best-effort; never raises) ----------------------------

    def record_resolve(
        self,
        *,
        engine: str,
        confidence: str,
        coverage: float,
        broadening: bool,
        deliveries: list[tuple[str, str, int]],
        delivered_tokens: int,
        offered_tokens: int,
        suppressed_tokens: int = 0,
        subject: str | None = None,
        project_id: str | None = None,
        traits_json: str | None = None,
    ) -> None:
        """Record one ``resolve_kits`` call plus its per-kit deliveries.

        :param deliveries: ``(kit, disposition, tokens)`` triples delivered by
            this resolve. Written with the new resolve's id so co-occurrence
            (which kits travelled together) is recoverable.
        :param suppressed_tokens: Always-load tokens omitted by session dedup
            (already delivered earlier this session); a context-saving figure.
        :param subject: The caller's stable IdP subject, when authenticated.
            ``None`` for unattributed/anonymous resolves. Feeds per-user
            memory derivation (see ``app.storage.user_memory``).
        :param project_id: Optional stable repo label from the caller's
            ``.quartermaster.toml`` (a telemetry grouping label only).
        :param traits_json: The four inferred trait lists, JSON-encoded, for
            per-user language/framework affinity derivation.
        """
        now = time.time()
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                cur = conn.execute(
                    "INSERT INTO resolve_events "
                    "(ts, engine, confidence, coverage, broadening, "
                    " delivered_tokens, offered_tokens, suppressed_tokens, "
                    " subject, project_id, traits_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        now,
                        engine,
                        confidence,
                        float(coverage),
                        1 if broadening else 0,
                        int(delivered_tokens),
                        int(offered_tokens),
                        int(suppressed_tokens),
                        subject,
                        project_id,
                        traits_json,
                    ),
                )
                resolve_id = cur.lastrowid
                if deliveries:
                    conn.executemany(
                        "INSERT INTO deliveries "
                        "(ts, kit, disposition, tokens, resolve_id) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [
                            (now, kit, disp, int(tokens), resolve_id)
                            for (kit, disp, tokens) in deliveries
                        ],
                    )
                conn.commit()
                self._after_write_locked()
        except Exception:  # noqa: BLE001 - metrics must never break a resolve
            logger.debug("record_resolve failed", exc_info=True)

    def record_delivery(
        self, *, kit: str, disposition: str, tokens: int
    ) -> None:
        """Record a standalone kit delivery (e.g. a direct ``get_kit`` call)."""
        now = time.time()
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                conn.execute(
                    "INSERT INTO deliveries "
                    "(ts, kit, disposition, tokens, resolve_id) "
                    "VALUES (?, ?, ?, ?, NULL)",
                    (now, kit, disposition, int(tokens)),
                )
                conn.commit()
                self._after_write_locked()
        except Exception:  # noqa: BLE001
            logger.debug("record_delivery failed", exc_info=True)

    def record_kit_version_use(
        self,
        *,
        kit: str,
        version: str,
        pinned: bool = False,
        advisory_shown: bool = False,
        subject: str | None = None,
        project_id: str | None = None,
        resolve_id: int | None = None,
    ) -> None:
        """Record which major version of a kit was served to a caller.

        Kept in its own table (not ``deliveries``, which feeds per-user
        memory and co-occurrence) so version/pin semantics stay isolated.
        Feeds the per-kit version-adoption chart and operator telemetry.

        :param kit: Kit name.
        :param version: The major version actually served (``v<N>``).
        :param pinned: Whether the served version came from a valid repo pin.
        :param advisory_shown: Whether a ``version_advisory`` was attached
            (i.e. a conservative default was applied).
        :param subject: The caller's stable IdP subject, when authenticated.
        :param project_id: Optional stable repo label (telemetry grouping).
        :param resolve_id: The owning ``resolve_events`` id, when this use
            came from a ``resolve_kits`` call; ``None`` for direct
            ``get_kit`` pulls.
        """
        if not self._version_telemetry_enabled:
            return
        now = time.time()
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                conn.execute(
                    "INSERT INTO kit_version_uses "
                    "(ts, subject, project_id, kit, version, pinned, "
                    " advisory_shown, resolve_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        now,
                        subject,
                        project_id,
                        kit,
                        version,
                        1 if pinned else 0,
                        1 if advisory_shown else 0,
                        resolve_id,
                    ),
                )
                conn.commit()
                self._after_write_locked()
        except Exception:  # noqa: BLE001 - telemetry must never break a resolve
            logger.debug("record_kit_version_use failed", exc_info=True)

    def record_tool_call(
        self, *, tool: str, ok: bool, duration_ms: float
    ) -> None:
        """Record one MCP tool invocation (name, outcome, duration)."""
        now = time.time()
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                conn.execute(
                    "INSERT INTO tool_calls (ts, tool, ok, duration_ms) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        now,
                        tool or "unknown",
                        1 if ok else 0,
                        float(duration_ms),
                    ),
                )
                conn.commit()
                self._after_write_locked()
        except Exception:  # noqa: BLE001
            logger.debug("record_tool_call failed", exc_info=True)

    def maybe_snapshot_catalog(self) -> None:
        """Write today's per-domain catalog snapshot if not already present.

        Opportunistic (no scheduler): the first event of each UTC day pays the
        catalog walk; subsequent calls short-circuit on the ``day`` check. Gives
        the catalog-growth series daily granularity across restarts.
        """
        day = time.strftime("%Y-%m-%d", time.gmtime())
        try:
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                row = conn.execute(
                    "SELECT 1 FROM catalog_snapshots WHERE day = ? LIMIT 1",
                    (day,),
                ).fetchone()
                if row is not None:
                    return
            # Compute the (potentially slow) stats outside the lock.
            stats = _compute_catalog_stats()
            if not stats:
                return
            with self._lock:
                conn = self._conn
                if conn is None:
                    return
                conn.executemany(
                    "INSERT OR REPLACE INTO catalog_snapshots "
                    "(day, domain, kits, sections, total_tokens, "
                    " always_load_tokens) VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        (
                            day,
                            domain,
                            s["kits"],
                            s["sections"],
                            s["total_tokens"],
                            s["always_load_tokens"],
                        )
                        for domain, s in stats.items()
                    ],
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            logger.debug("maybe_snapshot_catalog failed", exc_info=True)

    def _after_write_locked(self) -> None:
        """Throttled prune; caller must hold the lock."""
        self._writes += 1
        if self._writes % _PRUNE_EVERY == 0:
            self._prune_locked()

    def _prune_locked(self) -> None:
        """Drop rows older than the retention window; caller holds the lock."""
        conn = self._conn
        if conn is None:
            return
        cutoff = time.time() - self._retention_seconds
        conn.execute("DELETE FROM resolve_events WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM deliveries WHERE ts < ?", (cutoff,))
        conn.execute("DELETE FROM tool_calls WHERE ts < ?", (cutoff,))
        conn.execute(
            "DELETE FROM kit_version_uses WHERE ts < ?", (cutoff,)
        )
        day_cutoff = time.strftime(
            "%Y-%m-%d", time.gmtime(cutoff - 86_400)
        )
        conn.execute(
            "DELETE FROM catalog_snapshots WHERE day < ?", (day_cutoff,)
        )
        conn.commit()

    def _migrate_locked(self) -> None:
        """Add columns introduced after initial release; caller holds the lock.

        ``CREATE TABLE IF NOT EXISTS`` leaves a pre-existing table unchanged,
        so new columns need an idempotent ``ALTER TABLE`` guard here. Old
        rows read back ``NULL`` for the new columns (unattributed).
        """
        conn = self._conn
        if conn is None:
            return
        cols = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(resolve_events)")
        }
        if "subject" not in cols:
            conn.execute("ALTER TABLE resolve_events ADD COLUMN subject TEXT")
        if "traits_json" not in cols:
            conn.execute(
                "ALTER TABLE resolve_events ADD COLUMN traits_json TEXT"
            )
        if "project_id" not in cols:
            conn.execute(
                "ALTER TABLE resolve_events ADD COLUMN project_id TEXT"
            )
        if "suppressed_tokens" not in cols:
            conn.execute(
                "ALTER TABLE resolve_events ADD COLUMN "
                "suppressed_tokens INTEGER NOT NULL DEFAULT 0"
            )
        conn.commit()

    def resolve_history_for_subject(
        self, sub: str, cutoff: float
    ) -> list[dict[str, Any]]:
        """Return *sub*'s resolve events (with delivered kits) since *cutoff*.

        Feeds per-user memory derivation (see ``app.storage.user_memory``):
        each item is ``{"ts", "traits_json", "kits"}`` where ``kits`` are the
        *delivered* (not merely offered) kit names for that resolve.
        """
        rows = self._query(
            "SELECT id, ts, traits_json FROM resolve_events "
            "WHERE subject = ? AND ts >= ? ORDER BY ts",
            (sub, cutoff),
        )
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" for _ in ids)
        delivery_rows = self._query(
            f"SELECT resolve_id, kit FROM deliveries "
            f"WHERE resolve_id IN ({placeholders}) "
            f"AND disposition IN ({','.join('?' for _ in _DELIVERED)})",
            (*ids, *_DELIVERED),
        )
        kits_by_resolve: dict[int, list[str]] = {}
        for row in delivery_rows:
            kits_by_resolve.setdefault(row["resolve_id"], []).append(row["kit"])
        return [
            {
                "ts": row["ts"],
                "traits_json": row["traits_json"],
                "kits": kits_by_resolve.get(row["id"], []),
            }
            for row in rows
        ]

    # -- read/aggregate path (used by the /api/metrics endpoint) -----------

    def _query(self, sql: str, params: tuple[Any, ...] = ()) -> list[Any]:
        with self._lock:
            conn = self._conn
            if conn is None:
                return []
            return conn.execute(sql, params).fetchall()

    def kit_usage(self, cutoff: float) -> list[dict[str, Any]]:
        """Per-kit delivery counts + delivered tokens, busiest first.

        Answers "which kits are used a lot / almost none". Counts only
        *delivered* dispositions (excludes ``offered``).
        """
        placeholders = ",".join("?" for _ in _DELIVERED)
        rows = self._query(
            f"SELECT kit, COUNT(*) AS deliveries, "
            f"COALESCE(SUM(tokens), 0) AS tokens "
            f"FROM deliveries "
            f"WHERE ts >= ? AND disposition IN ({placeholders}) "
            f"GROUP BY kit ORDER BY deliveries DESC, kit ASC",
            (cutoff, *_DELIVERED),
        )
        return [
            {
                "kit": r["kit"],
                "deliveries": r["deliveries"],
                "tokens": r["tokens"],
            }
            for r in rows
        ]

    def tokens_timeseries(
        self, cutoff: float, granularity: str = "1d"
    ) -> list[dict[str, Any]]:
        """Per-bucket delivered vs offered vs suppressed tokens.

        ``suppressed`` is the always-load content session dedup kept out of the
        caller's context (a saving, not a delivery). *granularity* selects the
        bucket size (``1h``/``1d``); the ``day`` key is an opaque, sorted bucket
        label (a date, or ``YYYY-MM-DD HH:00`` hourly).
        """
        fmt = _GRANULARITY_FORMATS.get(granularity, _GRANULARITY_FORMATS["1d"])
        rows = self._query(
            f"SELECT strftime('{fmt}', ts, 'unixepoch') AS day, "
            "disposition, COALESCE(SUM(tokens), 0) AS tokens "
            "FROM deliveries WHERE ts >= ? "
            "GROUP BY day, disposition ORDER BY day ASC",
            (cutoff,),
        )
        by_day: dict[str, dict[str, int]] = {}
        for r in rows:
            bucket = by_day.setdefault(
                r["day"], {"delivered": 0, "offered": 0, "suppressed": 0}
            )
            if r["disposition"] == "offered":
                bucket["offered"] += r["tokens"]
            elif r["disposition"] == "suppressed":
                bucket["suppressed"] += r["tokens"]
            else:
                bucket["delivered"] += r["tokens"]
        return [
            {
                "day": day,
                "delivered": v["delivered"],
                "offered": v["offered"],
                "suppressed": v["suppressed"],
            }
            for day, v in sorted(by_day.items())
        ]

    def version_adoption(
        self, kit: str, cutoff: float, granularity: str = "1d"
    ) -> dict[str, Any]:
        """Per-bucket count of which major versions of *kit* were served.

        Powers the per-kit version-adoption chart on the kit detail page.
        Reads ``kit_version_uses`` (never ``deliveries``). *granularity*
        selects the bucket size (``1h``/``1d``); the ``day`` key is an
        opaque, sorted bucket label.

        :returns: ``{"granularity", "versions": [...], "buckets":
            [{"day", "counts": {version: n}}]}`` with ``versions`` sorted
            oldest → newest across the window.
        """
        fmt = _GRANULARITY_FORMATS.get(granularity, _GRANULARITY_FORMATS["1d"])
        rows = self._query(
            f"SELECT strftime('{fmt}', ts, 'unixepoch') AS day, "
            "version, COUNT(*) AS uses "
            "FROM kit_version_uses WHERE kit = ? AND ts >= ? "
            "GROUP BY day, version ORDER BY day ASC",
            (kit, cutoff),
        )
        by_day: dict[str, dict[str, int]] = {}
        versions: set[str] = set()
        for r in rows:
            versions.add(r["version"])
            by_day.setdefault(r["day"], {})[r["version"]] = r["uses"]
        ordered_versions = sorted(
            versions, key=lambda v: _version_sort_key(v)
        )
        buckets = [
            {"day": day, "counts": by_day[day]}
            for day in sorted(by_day)
        ]
        return {
            "granularity": granularity,
            "versions": ordered_versions,
            "buckets": buckets,
        }

    def resolve_health(self, cutoff: float) -> dict[str, Any]:
        """Engine/confidence mix, coverage percentiles, broadening rate."""
        engine_rows = self._query(
            "SELECT engine, COUNT(*) AS n FROM resolve_events "
            "WHERE ts >= ? GROUP BY engine",
            (cutoff,),
        )
        conf_rows = self._query(
            "SELECT confidence, COUNT(*) AS n FROM resolve_events "
            "WHERE ts >= ? GROUP BY confidence",
            (cutoff,),
        )
        cov_rows = self._query(
            "SELECT coverage, broadening FROM resolve_events WHERE ts >= ?",
            (cutoff,),
        )
        coverages = [
            r["coverage"] for r in cov_rows if r["coverage"] is not None
        ]
        total = len(cov_rows)
        broadening = sum(1 for r in cov_rows if r["broadening"])
        return {
            "total_calls": total,
            "engine_mix": {
                (r["engine"] or "unknown"): r["n"] for r in engine_rows
            },
            "confidence_mix": {
                (r["confidence"] or "unknown"): r["n"] for r in conf_rows
            },
            "coverage_p50": _percentile(coverages, 0.5),
            "coverage_p95": _percentile(coverages, 0.95),
            "broadening_rate": (broadening / total) if total else 0.0,
        }

    def tool_latency(self, cutoff: float) -> list[dict[str, Any]]:
        """Per-tool call count, error count, p50/p95 latency (ms)."""
        rows = self._query(
            "SELECT tool, ok, duration_ms FROM tool_calls WHERE ts >= ?",
            (cutoff,),
        )
        by_tool: dict[str, dict[str, Any]] = {}
        for r in rows:
            entry = by_tool.setdefault(
                r["tool"], {"durations": [], "errors": 0}
            )
            entry["durations"].append(r["duration_ms"])
            if not r["ok"]:
                entry["errors"] += 1
        out = [
            {
                "tool": tool,
                "calls": len(entry["durations"]),
                "errors": entry["errors"],
                "p50_ms": _percentile(entry["durations"], 0.5),
                "p95_ms": _percentile(entry["durations"], 0.95),
            }
            for tool, entry in by_tool.items()
        ]
        out.sort(key=lambda e: e["calls"], reverse=True)
        return out

    def co_occurrence(self, cutoff: float) -> dict[str, Any]:
        """Behavioural distinctness: how often two kits are delivered together.

        Built from the distinct ``(resolve_id, kit)`` set so a kit inlined *and*
        offered in one resolve counts once. Cell value is the Jaccard ratio
        ``together / (times_a + times_b - together)`` in ``[0, 1]``;
        ``count`` is the raw co-occurrence for tooltips.
        """
        rows = self._query(
            "SELECT DISTINCT resolve_id, kit FROM deliveries "
            "WHERE ts >= ? AND resolve_id IS NOT NULL",
            (cutoff,),
        )
        by_resolve: dict[int, set[str]] = {}
        for r in rows:
            by_resolve.setdefault(r["resolve_id"], set()).add(r["kit"])

        singles: dict[str, int] = {}
        pairs: dict[tuple[str, str], int] = {}
        for kit_set in by_resolve.values():
            members = sorted(kit_set)
            for kit in members:
                singles[kit] = singles.get(kit, 0) + 1
            for i, a in enumerate(members):
                for b in members[i + 1 :]:
                    pairs[(a, b)] = pairs.get((a, b), 0) + 1

        kits = sorted(singles)
        index = {kit: i for i, kit in enumerate(kits)}
        cells: list[dict[str, Any]] = []
        for (a, b), count in pairs.items():
            union = singles[a] + singles[b] - count
            jaccard = (count / union) if union else 0.0
            cells.append(
                {"x": index[a], "y": index[b], "value": jaccard, "count": count}
            )
            cells.append(
                {"x": index[b], "y": index[a], "value": jaccard, "count": count}
            )
        return {"kits": kits, "cells": cells}

    def catalog_growth(
        self, cutoff: float, granularity: str = "1d"
    ) -> dict[str, Any]:
        """Per-bucket, per-domain catalog token mass, with delivered overlaid.

        Tells the "flattening" story: catalog mass can climb per domain while
        delivered volume for established domains stays flat. Catalog snapshots
        are stored once per UTC day, so under hourly *granularity* each day's
        snapshot is forward-filled across that day's hourly buckets — the
        catalog area holds flat while the delivered line moves — keeping both
        series on one aligned x-axis.
        """
        fmt = _GRANULARITY_FORMATS.get(granularity, _GRANULARITY_FORMATS["1d"])
        day_cutoff = time.strftime("%Y-%m-%d", time.gmtime(cutoff))
        snap_rows = self._query(
            "SELECT day, domain, total_tokens, always_load_tokens "
            "FROM catalog_snapshots WHERE day >= ? ORDER BY day ASC",
            (day_cutoff,),
        )
        if granularity == "1h":
            catalog = self._catalog_snapshots_hourly(snap_rows, cutoff)
        else:
            catalog = [
                {
                    "day": r["day"],
                    "domain": r["domain"],
                    "total_tokens": r["total_tokens"],
                    "always_load_tokens": r["always_load_tokens"],
                }
                for r in snap_rows
            ]

        # Delivered tokens per bucket per domain: map kit -> domains at query
        # time (the catalog is small) since deliveries carry no domain column.
        kit_to_domains = kit_domain_map()
        del_rows = self._query(
            f"SELECT strftime('{fmt}', ts, 'unixepoch') AS day, kit, "
            "COALESCE(SUM(tokens), 0) AS tokens FROM deliveries "
            "WHERE ts >= ? AND disposition IN "
            "('inlined', 'full', 'sections') GROUP BY day, kit",
            (cutoff,),
        )
        delivered: dict[tuple[str, str], int] = {}
        for r in del_rows:
            for domain in kit_to_domains.get(r["kit"], ["unknown"]):
                delivered[(r["day"], domain)] = (
                    delivered.get((r["day"], domain), 0) + r["tokens"]
                )
        delivered_series = [
            {"day": day, "domain": domain, "tokens": tokens}
            for (day, domain), tokens in sorted(delivered.items())
        ]
        return {"catalog": catalog, "delivered": delivered_series}

    @staticmethod
    def _catalog_snapshots_hourly(
        snap_rows: list[Any], cutoff: float
    ) -> list[dict[str, Any]]:
        """Forward-fill daily catalog snapshots across hourly buckets.

        Steps ``cutoff → now`` in whole hours and emits, for each hourly bucket,
        the snapshot of the UTC day it falls in — so the catalog area stays flat
        within a day while aligning to the hourly delivered series.
        """
        by_day: dict[str, list[Any]] = {}
        for r in snap_rows:
            by_day.setdefault(r["day"], []).append(r)
        if not by_day:
            return []
        out: list[dict[str, Any]] = []
        now = time.time()
        step = int(cutoff - (cutoff % 3600))  # align to top of the hour
        while step <= now:
            day = time.strftime("%Y-%m-%d", time.gmtime(step))
            bucket = time.strftime("%Y-%m-%d %H:00", time.gmtime(step))
            for r in by_day.get(day, ()):
                out.append(
                    {
                        "day": bucket,
                        "domain": r["domain"],
                        "total_tokens": r["total_tokens"],
                        "always_load_tokens": r["always_load_tokens"],
                    }
                )
            step += 3600
        return out


# ---------------------------------------------------------------------------
# Catalog-derived helpers (independent of the DB and of OTEL)
# ---------------------------------------------------------------------------


def _kit_trait_sets() -> dict[str, set[str]]:
    """Return each kit's declared trait set (languages/frameworks/contexts/
    domains + hard ``requires``), namespaced so identical values in different
    categories don't collide. Used for structural distinctness."""
    from app.kits import iter_catalog

    sets: dict[str, set[str]] = {}
    for info, applicability in iter_catalog():
        traits: set[str] = set()
        for category, values in (
            ("lang", applicability.languages),
            ("fw", applicability.frameworks),
            ("ctx", applicability.contexts),
            ("dom", applicability.domains),
        ):
            for value in values or []:
                traits.add(f"{category}:{value}")
        for category, values in (applicability.requires or {}).items():
            for value in values or []:
                traits.add(f"req-{category}:{value}")
        sets[info.name] = traits
    return sets


def structural_overlap() -> dict[str, Any]:
    """Structural distinctness: pairwise trait-set Jaccard across the catalog.

    Static (needs no usage data), so it works on day one. A bright off-diagonal
    cell = two kits claim overlapping applicability → possible redundancy.
    """
    try:
        sets = _kit_trait_sets()
    except Exception:  # noqa: BLE001
        logger.debug("structural_overlap failed", exc_info=True)
        return {"kits": [], "cells": []}
    kits = sorted(sets)
    cells: list[dict[str, Any]] = []
    for i, a in enumerate(kits):
        for j in range(i + 1, len(kits)):
            b = kits[j]
            sa, sb = sets[a], sets[b]
            union = sa | sb
            jaccard = (len(sa & sb) / len(union)) if union else 0.0
            cells.append({"x": i, "y": j, "value": jaccard})
            cells.append({"x": j, "y": i, "value": jaccard})
    return {"kits": kits, "cells": cells}


def kit_domain_map() -> dict[str, list[str]]:
    """Map kit name -> declared domains (``["unknown"]`` when none)."""
    try:
        from app.kits import iter_catalog

        return {
            info.name: (applicability.domains or ["unknown"])
            for info, applicability in iter_catalog()
        }
    except Exception:  # noqa: BLE001
        return {}


def _compute_catalog_stats() -> dict[str, dict[str, int]]:
    """Per-domain kit/section/token tallies for the daily snapshot.

    Walks the catalog like ``telemetry._compute_catalog_stats`` but returns
    plain dicts and lives here so the local store never depends on OTEL being
    importable/initialised.
    """
    from app.kits import iter_catalog, read_kit, read_kit_outline
    from app.tokens import count_tokens, estimate_tokens_from_bytes

    stats: dict[str, dict[str, int]] = {}

    def _bucket(domain: str) -> dict[str, int]:
        return stats.setdefault(
            domain,
            {
                "kits": 0,
                "sections": 0,
                "total_tokens": 0,
                "always_load_tokens": 0,
            },
        )

    for info, applicability in iter_catalog():
        domains = applicability.domains or ["unknown"]
        for domain in domains:
            _bucket(domain)["kits"] += 1
        outline = read_kit_outline(info.name)
        version = outline["version"]
        for section in outline["sections"]:
            try:
                body = read_kit(info.name, version, [section["id"]])
                toks = count_tokens(body)
            except Exception:  # noqa: BLE001
                toks = estimate_tokens_from_bytes(section["bytes"])
            for domain in domains:
                entry = _bucket(domain)
                entry["sections"] += 1
                entry["total_tokens"] += toks
                if section["always_load"]:
                    entry["always_load_tokens"] += toks
    return stats


# ---------------------------------------------------------------------------
# Module-level singleton + best-effort tap helpers (called from request paths)
# ---------------------------------------------------------------------------

_store: LocalMetricsStore | None = None
_init_lock = threading.Lock()

# Window aliases accepted by the API; each maps to a number of seconds. The
# effective window is capped to the configured retention.
_WINDOWS: dict[str, int] = {
    "24h": 24 * 3600,
    "7d": 7 * 86_400,
    "30d": 30 * 86_400,
}
DEFAULT_WINDOW = "7d"

# Time-series bucket sizes accepted by the API; each maps to the ``strftime``
# format that groups a Unix timestamp into that bucket. Hourly is useful for
# watching the 24h window evolve live; daily is the long-view default.
_GRANULARITY_FORMATS: dict[str, str] = {
    "1h": "%Y-%m-%d %H:00",
    "1d": "%Y-%m-%d",
}
DEFAULT_GRANULARITY = "1d"


def init(settings: Any) -> LocalMetricsStore | None:
    """Initialise the process-wide store from settings; idempotent.

    Returns ``None`` (and records nothing thereafter) when
    ``metrics_local_enabled`` is false or initialisation fails.
    """
    global _store
    with _init_lock:
        if _store is not None:
            return _store
        if not getattr(settings, "metrics_local_enabled", True):
            return None
        try:
            store = LocalMetricsStore(
                db_path=getattr(settings, "metrics_local_db_path"),
                retention_days=getattr(
                    settings, "metrics_local_retention_days", 7
                ),
                version_telemetry_enabled=getattr(
                    settings, "version_telemetry_enabled", True
                ),
            )
            store.init()
            _store = store
            return _store
        except Exception:  # noqa: BLE001 - never block app startup on metrics
            logger.warning("local metrics store init failed", exc_info=True)
            return None


def get_store() -> LocalMetricsStore | None:
    """Return the initialised store, or ``None`` if disabled/unavailable."""
    return _store


def reset_for_tests() -> None:
    """Drop the process-wide store (test hook only)."""
    global _store
    with _init_lock:
        if _store is not None:
            _store.close()
        _store = None


def retention_days() -> int:
    """Retention of the active store in days (0 when no store)."""
    store = _store
    return (
        int(store._retention_seconds // 86_400) if store is not None else 0
    )


def record_resolve(**kwargs: Any) -> None:
    """Best-effort tap: forward a resolve event to the store if enabled."""
    store = _store
    if store is not None:
        store.record_resolve(**kwargs)


def record_delivery(**kwargs: Any) -> None:
    """Best-effort tap: forward a standalone delivery to the store."""
    store = _store
    if store is not None:
        store.record_delivery(**kwargs)


def record_kit_version_use(**kwargs: Any) -> None:
    """Best-effort tap: forward a kit version-use event to the store."""
    store = _store
    if store is not None:
        store.record_kit_version_use(**kwargs)


def record_tool_call(**kwargs: Any) -> None:
    """Best-effort tap: forward a tool call to the store."""
    store = _store
    if store is not None:
        store.record_tool_call(**kwargs)


def maybe_snapshot_catalog() -> None:
    """Best-effort tap: let the store take today's catalog snapshot."""
    store = _store
    if store is not None:
        store.maybe_snapshot_catalog()
