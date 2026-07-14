"""Agent-in-the-loop clarification for ``resolve_kits``.

Trait inference can be *partial*: a task like "add a database" yields the
``database`` capability but no ``languages`` trait, yet a C# project and a
Python project want different database kits. In that case some candidate kits
declare a hard ``requires.<dimension>`` the task never provided — the selector
flags them ``uncertain`` with a ``need-trait:<dimension>`` reason
(:func:`app.kits._evaluate_candidate`) — and the recommendation cannot be made
confidently.

:func:`detect_clarification` turns that situation into a structured, *non-
blocking* clarification signal: which trait dimensions are missing, which kits
are blocked on each, and the legal values that would unblock them. The resolver
renders this into a ``clarification`` block that the calling agent answers
itself from repo inspection (``*.csproj``→csharp, ``pyproject.toml``→python,
``package.json``→javascript/typescript) before re-resolving — distinct from,
and taking precedence over, the human ``ctx.elicit`` path in ``app.main``.

This is the mirror image of :mod:`app.gap`: gap fires only when inference found
*nothing* (``not inferred.has_any()``); clarification fires only when inference
found *something* but a pivotal dimension is still missing. The two are
mutually exclusive by construction and neither touches
:func:`app.kits.select_kits_v2`'s own thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.traits import TraitVocabulary

# Ask about the highest-weight missing dimension first. Mirrors the selector's
# own trait weights (WEIGHT_LANGUAGES > FRAMEWORKS > CAPABILITIES > CONTEXTS in
# app/kits.py): the language usually flips the recommendation the most.
_DIMENSION_PRIORITY = ("languages", "frameworks", "capabilities", "contexts")


@dataclass(frozen=True)
class ClarifyQuestion:
    """One missing pivotal trait dimension the agent should resolve.

    :param category: The trait dimension to ask about, one of
        ``languages``/``frameworks``/``capabilities``/``contexts``.
    :param options: Legal answers, narrowed to the values the blocking kits
        actually require (intersected with the catalog vocabulary); falls back
        to the whole category vocabulary when no narrowing is possible.
    :param blocking_kits: Names of the selected candidates that cannot be
        confidently recommended until this dimension is known.
    :param why: Short human-readable reason naming the blocking kits.
    """

    category: str
    options: list[str]
    blocking_kits: list[str]
    why: str


@dataclass(frozen=True)
class ClarifySignal:
    """A confirmed need for clarification before kits can be recommended.

    :param questions: Ordered questions (highest-weight dimension first),
        capped at ``clarification_max_questions``.
    :param reason: Always ``"pivotal-trait-missing"`` for now; kept as a field
        so future detectors can report a different reason.
    """

    questions: list[ClarifyQuestion]
    reason: str


def detect_clarification(
    *,
    selection: dict[str, Any],
    inferred: dict[str, list[str]],
    vocab: TraitVocabulary,
    settings: Any = None,
) -> ClarifySignal | None:
    """Return a :class:`ClarifySignal` when a pivotal trait is missing.

    Returns ``None`` when no clarification is warranted. Callers should invoke
    this only when trait inference already found
    *something* (``inferred.has_any()``); the empty case is handled by
    :func:`app.gap.detect_gap` instead, so the two never collide.

    :param selection: The :func:`app.kits.select_kits_v2` return dict. Each
        candidate is expected to carry ``reasons`` and ``needs``.
    :param inferred: The inferred traits as ``{category: [values]}``. A
        dimension already present here is never asked about — that is also the
        loop-breaker: once the agent folds an answer into the task and
        re-resolves, the dimension is inferred and the question does not recur.
    :param vocab: The catalog trait vocabulary, used to bound the offered
        answer ``options``.
    :param settings: App settings; defaults to :func:`app.config.get_settings`.
        Tolerates an incompletely configured environment (returns ``None``) so
        this can never break a resolve.
    """
    if settings is None:
        from pydantic import ValidationError

        try:
            settings = get_settings()
        except ValidationError:
            return None

    if not getattr(settings, "clarification_enabled", True):
        return None

    # Note: we deliberately do NOT gate on the aggregate ``confidence`` here.
    # A task like "add a database" covers its single inferred dimension fully
    # and so scores "high", yet is exactly the case a missing language should
    # clarify. The presence of a ``need-trait`` reason on a selected candidate
    # (below) is the precise, sufficient signal; a confidence gate would only
    # mask it.
    candidates = selection.get("candidates") or []
    if not candidates:
        return None

    max_questions = getattr(settings, "clarification_max_questions", 2)
    min_blocking = getattr(settings, "clarification_min_blocking_kits", 1)
    vocab_by_category = vocab.all_by_category()

    questions: list[ClarifyQuestion] = []
    for dimension in _DIMENSION_PRIORITY:
        if len(questions) >= max_questions:
            break
        # Skip a dimension the task already provided (loop-breaker).
        if inferred.get(dimension):
            continue

        need_reason = f"need-trait:{dimension}"
        blocking = [
            candidate
            for candidate in candidates
            if need_reason in candidate.get("reasons", [])
        ]
        if len(blocking) < min_blocking:
            continue

        blocking_kits = [candidate["name"] for candidate in blocking]
        # Narrow the offered options to exactly the values these kits require,
        # bounded by the catalog vocabulary; fall back to the whole category.
        allowed = set(vocab_by_category.get(dimension, []))
        required: set[str] = set()
        for candidate in blocking:
            required.update(candidate.get("needs", {}).get(dimension, []))
        options = sorted(required & allowed) or sorted(allowed)

        noun = dimension[:-1] if dimension.endswith("s") else dimension
        why = (
            f"{', '.join(blocking_kits)} require a specific {noun} before "
            "they can be confidently recommended."
        )
        questions.append(
            ClarifyQuestion(
                category=dimension,
                options=options,
                blocking_kits=blocking_kits,
                why=why,
            )
        )

    if not questions:
        return None
    return ClarifySignal(questions=questions, reason="pivotal-trait-missing")
