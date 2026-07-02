"""Bounded, familiarity-based personalization for ``resolve_kits`` ranking.

Nudges the already-scored candidate list from :func:`app.kits.select_kits_v2`
using a per-caller memory profile (see :mod:`app.storage.user_memory`), as a
strictly bounded tie-breaker — never a filter. The bonus cap
(:data:`MEMORY_BONUS_CAP`) is set below the smallest real trait weight
(``WEIGHT_CONTEXTS = 10`` in :mod:`app.kits`), so a kit that matches even one
genuine trait always outranks a merely-familiar kit with no real match. This
is what prevents "tunnel vision": a caller can never be nudged away from
content outside their usual pattern, only re-sorted among near-ties.
"""

from __future__ import annotations

from typing import Any

from app.kits import iter_catalog

# Strictly below WEIGHT_CONTEXTS (10, the smallest positive trait weight in
# app.kits) so the nudge can only reorder candidates whose base scores are
# already within this many points of each other.
MEMORY_BONUS_CAP = 8
_KIT_BONUS = 3
_DOMAIN_BONUS = 2
_LANGUAGE_BONUS = 2
_FRAMEWORK_BONUS = 1


def _kit_applicability_map() -> dict[str, Any]:
    """Return ``{kit_name: applicability}`` for the whole catalog."""
    return {info.name: applicability for info, applicability in iter_catalog()}


def _bonus_for(
    candidate: dict[str, Any],
    profile: dict[str, Any],
    applicability_by_name: dict[str, Any],
) -> int:
    """Return the clamped familiarity bonus for one candidate."""
    bonus = 0
    if candidate["name"] in profile.get("top_kits", []):
        bonus += _KIT_BONUS

    applicability = applicability_by_name.get(candidate["name"])
    if applicability is not None:
        if set(applicability.domains or []) & set(
            profile.get("top_domains", [])
        ):
            bonus += _DOMAIN_BONUS
        if set(applicability.languages or []) & set(
            profile.get("top_languages", [])
        ):
            bonus += _LANGUAGE_BONUS
        if set(applicability.frameworks or []) & set(
            profile.get("top_frameworks", [])
        ):
            bonus += _FRAMEWORK_BONUS

    return min(bonus, MEMORY_BONUS_CAP)


def apply_memory_nudge(
    candidates: list[dict[str, Any]], profile: dict[str, Any] | None
) -> list[dict[str, Any]]:
    """Return *candidates* re-sorted with a capped, additive familiarity bonus.

    Reorders only — never adds, removes, or changes a candidate's own
    ``score``. When *profile* is ``None`` or empty (no memory, or the caller
    has no history yet), returns *candidates* unchanged.

    :param candidates: The ranked candidate list from
        ``select_kits_v2()["candidates"]``.
    :param profile: A profile from :func:`app.storage.user_memory.get_or_build`,
        or ``None``.
    """
    if not profile:
        return candidates

    applicability_by_name = _kit_applicability_map()
    scored = [
        (candidate, _bonus_for(candidate, profile, applicability_by_name))
        for candidate in candidates
    ]
    scored.sort(key=lambda cb: (-(cb[0]["score"] + cb[1]), cb[0]["name"]))
    return [candidate for candidate, _ in scored]


def profile_hint(profile: dict[str, Any] | None) -> str:
    """Return a short, advisory hint line derived from a memory profile.

    Purely informational context for trait-inference prompts (sampling/LLM):
    the closed trait vocabulary stays authoritative, and this hint never
    names a specific kit — only trait-shaped context (languages, frameworks,
    domains) a task's wording might not fully surface on its own. Empty
    string when there is nothing to say.
    """
    if not profile:
        return ""
    parts: list[str] = []
    parts.extend(profile.get("top_languages", []))
    parts.extend(profile.get("top_frameworks", []))
    parts.extend(profile.get("top_domains", []))
    if not parts:
        return ""
    joined = ", ".join(dict.fromkeys(parts))
    return (
        f"Recurring context for this user: {joined} "
        "(advisory only; do not force-fit if the task doesn't match)."
    )
