"""File-backed, derived per-user memory (IdP subject -> familiarity profile).

A profile is a small, capped summary of what a subject's ``resolve_kits``
history tends to touch — a handful of domains/kits/languages/frameworks,
most-recent-weighted. It exists purely to *nudge* future kit ranking as a
bounded tie-breaker (see ``app.personalization``); it never filters or
excludes kits, so a subject can never be cut off from content outside their
usual pattern.

The profile is a **derived cache**, not a source of truth: it is rebuilt
from :class:`~app.observability.local_store.LocalMetricsStore` history on
demand (see :func:`get_or_build`), so this file can always be safely deleted.
Persistence mirrors :mod:`app.storage.role_store` (TOML, subject-keyed,
written atomically via :func:`atomic_write_text`).

Record schema (per subject)::

    [ "<sub>" ]
    updated = "<iso8601>"
    top_domains = ["auth", "rest-api"]
    top_kits = ["module-auth-oidc"]
    top_languages = ["python"]
    top_frameworks = ["fastapi"]
"""

from __future__ import annotations

import json
import math
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import tomli_w

from app.observability.local_store import LocalMetricsStore, kit_domain_map
from app.storage.kit_writes import atomic_write_text

_EMPTY_PROFILE_LISTS = (
    "top_domains",
    "top_kits",
    "top_languages",
    "top_frameworks",
)


@dataclass(frozen=True)
class ProfileCaps:
    """Maximum entries kept per category — what keeps a profile small."""

    domains: int = 5
    kits: int = 5
    languages: int = 3
    frameworks: int = 3


def _load(path: Path) -> dict[str, dict[str, Any]]:
    """Load the subject->record mapping (empty when the file is absent)."""
    if not path.exists():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if isinstance(v, dict)}


def _save(path: Path, records: dict[str, dict[str, Any]]) -> None:
    """Persist *records* atomically as TOML."""
    atomic_write_text(path, tomli_w.dumps(records))


def _parse_iso(value: str) -> float:
    """Return the Unix timestamp for an ISO-8601 string."""
    return datetime.fromisoformat(value).timestamp()


def _empty_profile(now: float) -> dict[str, Any]:
    return {
        "updated": datetime.fromtimestamp(now, tz=UTC).isoformat(
            timespec="seconds"
        ),
        "top_domains": [],
        "top_kits": [],
        "top_languages": [],
        "top_frameworks": [],
    }


def empty_profile() -> dict[str, Any]:
    """Return the shape of a not-yet-derived profile (no timestamp).

    Used by callers (the memory-viewing MCP tool / REST endpoint) that need
    a consistent response shape for a subject with no history yet, distinct
    from :func:`_empty_profile`'s failure-fallback (which stamps a real
    timestamp so a rebuilt-but-empty profile still has a valid cache key).
    """
    return {
        "updated": None,
        "top_domains": [],
        "top_kits": [],
        "top_languages": [],
        "top_frameworks": [],
    }


def load_profile(path: Path, sub: str) -> dict[str, Any] | None:
    """Return *sub*'s stored profile, or ``None`` if never derived."""
    return _load(path).get(sub)


def save_profile(path: Path, sub: str, profile: dict[str, Any]) -> None:
    """Persist *profile* for *sub*, overwriting any existing record."""
    records = _load(path)
    records[sub] = profile
    _save(path, records)


def clear_profile(path: Path, sub: str) -> bool:
    """Delete *sub*'s stored profile. Idempotent.

    :returns: ``True`` if a record was deleted.
    """
    records = _load(path)
    if sub in records:
        del records[sub]
        _save(path, records)
        return True
    return False


def _top(weights: dict[str, float], n: int) -> list[str]:
    """Return the *n* highest-weighted keys, ties broken lexically."""
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    return [key for key, _ in ranked[:n]]


def derive_profile(
    store: LocalMetricsStore,
    sub: str,
    *,
    now: float,
    half_life_days: float,
    caps: ProfileCaps,
) -> dict[str, Any]:
    """Deterministically rebuild *sub*'s profile from metrics history.

    Every event is weighted by ``exp(-age / half_life)`` so recent resolves
    dominate; frequencies are tallied per category and truncated to *caps*.
    No LLM call — pure arithmetic over data the metrics store already has.
    """
    half_life_seconds = max(1.0, half_life_days) * 86_400
    domains_by_kit = kit_domain_map()

    domain_weight: dict[str, float] = {}
    kit_weight: dict[str, float] = {}
    lang_weight: dict[str, float] = {}
    fw_weight: dict[str, float] = {}

    for event in store.resolve_history_for_subject(sub, 0.0):
        age = max(0.0, now - event["ts"])
        weight = math.exp(-age / half_life_seconds)

        for kit in event["kits"]:
            kit_weight[kit] = kit_weight.get(kit, 0.0) + weight
            for domain in domains_by_kit.get(kit, []):
                domain_weight[domain] = domain_weight.get(domain, 0.0) + weight

        traits: dict[str, Any] = {}
        if event["traits_json"]:
            try:
                traits = json.loads(event["traits_json"])
            except ValueError:
                traits = {}
        for lang in traits.get("languages", []):
            lang_weight[lang] = lang_weight.get(lang, 0.0) + weight
        for fw in traits.get("frameworks", []):
            fw_weight[fw] = fw_weight.get(fw, 0.0) + weight

    return {
        "updated": datetime.fromtimestamp(now, tz=UTC).isoformat(
            timespec="seconds"
        ),
        "top_domains": _top(domain_weight, caps.domains),
        "top_kits": _top(kit_weight, caps.kits),
        "top_languages": _top(lang_weight, caps.languages),
        "top_frameworks": _top(fw_weight, caps.frameworks),
    }


def get_or_build(
    path: Path,
    sub: str,
    store: LocalMetricsStore,
    *,
    ttl_seconds: float,
    half_life_days: float,
    caps: ProfileCaps,
    now: float,
) -> dict[str, Any]:
    """Return *sub*'s cached profile, rebuilding it if missing or stale.

    Best-effort: any failure (derivation error, corrupt cache) returns an
    empty profile rather than raising, mirroring the metrics store's own
    "never break a resolve" rule — a broken profile must never fail a
    ``resolve_kits`` call.
    """
    try:
        existing = load_profile(path, sub)
        if existing is not None:
            updated = existing.get("updated")
            if updated and now - _parse_iso(updated) < ttl_seconds:
                return existing

        profile = derive_profile(
            store, sub, now=now, half_life_days=half_life_days, caps=caps
        )
        save_profile(path, sub, profile)
        return profile
    except Exception:  # noqa: BLE001 - memory must never break a resolve
        return _empty_profile(now)
