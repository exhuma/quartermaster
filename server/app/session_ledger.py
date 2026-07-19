"""In-memory, per-session ledger of already-inlined ``always_load`` sections.

``resolve_kits`` inlines each selected kit's ``always_load`` sections into the
caller's context. Because kits are resolved *per task* (re-run whenever the work
changes shape), the same sections would otherwise be re-inlined into the same
conversation repeatedly, permanently occupying the context window. This ledger
records, per **MCP session** (~ one conversation / context window), which
``(kit, version, section_id)`` triples were already inlined, so a repeat resolve
can omit them and point back to them instead.

The ledger is deliberately **in-memory, per-process, and disposable**: it must
not persist across restarts (a restart harmlessly re-inlines once) and gates a
hot path, so it is a plain dict + lock rather than a persisted store. It is
keyed on the session id, *not* the user subject — a subject spans conversations,
so subject-keying would wrongly suppress content in a fresh context window.

Every operation is best-effort and never raises: on any error the ledger reports
"nothing already delivered", which degrades to the previous inline-everything
behaviour. Suppression can therefore only ever affect a section that was
recorded as inlined at least once in the same session.
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

DEFAULT_TTL_SECONDS = 3600
DEFAULT_MAX_SESSIONS = 2048

# A delivered section is identified across kit majors by name + version + id.
_SectionKey = tuple[str, str, str]


@dataclass
class _SessionEntry:
    """One tracked session: its last-touch time and delivered section keys."""

    last_seen: float
    delivered: set[_SectionKey] = field(default_factory=set)


class SessionDeliveryLedger:
    """Tracks which kit sections were already inlined per MCP session.

    Access is guarded by a lock because the synchronous resolver runs in a
    worker thread (``asyncio.to_thread``) and concurrent resolves share this
    singleton. Sessions expire after ``ttl_seconds`` of inactivity and are
    capped at ``max_sessions`` (least-recently-used evicted first).
    """

    def __init__(
        self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS,
        max_sessions: int = DEFAULT_MAX_SESSIONS,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max(1, max_sessions)
        self._sessions: OrderedDict[str, _SessionEntry] = OrderedDict()
        self._lock = threading.Lock()

    def filter_already_delivered(
        self, session_id: str | None, kit: str, version: str,
        section_ids: list[str], now: float | None = None,
    ) -> tuple[list[str], list[str]]:
        """Split *section_ids* into (fresh, already-delivered) for a session.

        Read-only apart from an LRU touch + lazy expiry; recording is deferred
        to :meth:`record_delivered` so the ledger only ever claims a section
        that was actually inlined. Returns everything as *fresh* when the
        session is unknown, dedup is not applicable, or anything goes wrong.
        """
        if not session_id or not section_ids:
            return list(section_ids), []
        try:
            ts = time.time() if now is None else now
            with self._lock:
                self._evict_locked(ts)
                entry = self._sessions.get(session_id)
                if entry is None:
                    return list(section_ids), []
                self._sessions.move_to_end(session_id)
                entry.last_seen = ts
                fresh: list[str] = []
                already: list[str] = []
                for sid in section_ids:
                    if (kit, version, sid) in entry.delivered:
                        already.append(sid)
                    else:
                        fresh.append(sid)
                return fresh, already
        except Exception:
            return list(section_ids), []

    def record_delivered(
        self, session_id: str | None, kit: str, version: str,
        section_ids: list[str], now: float | None = None,
    ) -> None:
        """Record that *section_ids* were inlined for *session_id* just now.

        Creates the session entry on first use, refreshes its recency, and
        enforces the TTL and size cap. Best-effort: swallows all errors.
        """
        if not session_id or not section_ids:
            return
        try:
            ts = time.time() if now is None else now
            with self._lock:
                self._evict_locked(ts)
                entry = self._sessions.get(session_id)
                if entry is None:
                    entry = _SessionEntry(last_seen=ts)
                    self._sessions[session_id] = entry
                self._sessions.move_to_end(session_id)
                entry.last_seen = ts
                for sid in section_ids:
                    entry.delivered.add((kit, version, sid))
                self._enforce_capacity_locked()
        except Exception:
            return

    def _evict_locked(self, now: float) -> None:
        """Drop sessions untouched for longer than the TTL. Lock held."""
        if self._ttl_seconds <= 0:
            return
        cutoff = now - self._ttl_seconds
        stale = [
            sid for sid, entry in self._sessions.items()
            if entry.last_seen < cutoff
        ]
        for sid in stale:
            self._sessions.pop(sid, None)

    def _enforce_capacity_locked(self) -> None:
        """Evict least-recently-used sessions past the cap. Lock held."""
        while len(self._sessions) > self._max_sessions:
            self._sessions.popitem(last=False)


_ledger: SessionDeliveryLedger | None = None
_init_lock = threading.Lock()


def get_ledger(settings: Any) -> SessionDeliveryLedger | None:
    """Return the process-wide ledger, or ``None`` when dedup is disabled.

    Lazily constructs the singleton from settings. Returns ``None`` (so the
    resolver inlines in full) when ``resolve_dedup_enabled`` is false or
    construction fails.
    """
    global _ledger
    if not getattr(settings, "resolve_dedup_enabled", True):
        return None
    if _ledger is not None:
        return _ledger
    with _init_lock:
        if _ledger is not None:
            return _ledger
        try:
            _ledger = SessionDeliveryLedger(
                ttl_seconds=getattr(
                    settings, "resolve_dedup_ttl_seconds", DEFAULT_TTL_SECONDS
                ),
                max_sessions=getattr(
                    settings, "resolve_dedup_max_sessions",
                    DEFAULT_MAX_SESSIONS,
                ),
            )
            return _ledger
        except Exception:
            return None


def reset_for_tests() -> None:
    """Drop the process-wide ledger (test hook only)."""
    global _ledger
    with _init_lock:
        _ledger = None
