"""Catalog-recall gap detection for ``resolve_kits``.

When trait inference finds nothing for a task (:meth:`InferredTraits.has_any`
is false), that could mean either (a) the catalog genuinely has nothing
relevant — a real gap worth reporting to a maintainer — or (b) the task's
wording just didn't hit an exact trait-vocabulary token even though the
catalog covers the topic (a ranking/inference miss, not a gap). Before
flagging a gap, :func:`detect_gap` runs one extra *fuzzy* recall pass over
every trait pseudo-document in the catalog (word overlap, or embedding
cosine similarity when available) to tell these two cases apart. This never
touches :func:`app.kits.select_kits_v2`'s own thresholds, so normal
resolution quality is unaffected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.traits import build_trait_docs

_WORD_RE = re.compile(r"[a-z0-9]+")
_TOP_N = 3
# Common filler words excluded from lexical recall so a match on "for" or
# "with" alone never masks a genuine catalog gap.
_STOPWORDS = {
    "a", "an", "the", "for", "to", "of", "in", "on", "with", "and", "or",
    "is", "are", "be", "this", "that", "it", "as", "by", "at", "from",
}


@dataclass(frozen=True)
class GapSignal:
    """A confirmed catalog gap: the task matched nothing meaningful.

    :param task: The original task text.
    :param best_recall_score: The single closest trait-document score found
        (word-overlap count, or cosine similarity when embeddings are used).
    :param matched_traits: The closest trait tokens by score (best-first),
        regardless of whether they crossed the recall threshold — useful
        context for a human reading the filed gap report.
    :param reason: Always ``"no-catalog-match"`` for now; kept as a field so
        future recall strategies can report a different reason.
    """

    task: str
    best_recall_score: float
    matched_traits: list[str]
    reason: str


def _tokenize(text: str) -> set[str]:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def _lexical_recall(task: str) -> tuple[float, list[str]]:
    """Return (best word-overlap count, closest trait tokens by overlap)."""
    task_words = _tokenize(task)
    scored: list[tuple[str, int]] = []
    for doc in build_trait_docs():
        overlap = len(task_words & _tokenize(doc.text))
        scored.append((doc.value, overlap))
    if not scored:
        return 0.0, []
    scored.sort(key=lambda vs: (-vs[1], vs[0]))
    best = float(scored[0][1])
    top = [value for value, score in scored[:_TOP_N] if score > 0]
    return best, top


def _embedding_recall(
    task: str, settings: Any
) -> tuple[float, list[str]] | None:
    """Return (best cosine similarity, closest trait tokens by score).

    ``None`` when no embedder is available, so the caller falls back to the
    lexical floor.
    """
    from app.embeddings import build_trait_embeddings, cosine, get_embedder

    embedder = get_embedder(settings)
    if embedder is None:
        return None

    trait_embeddings = build_trait_embeddings(
        embedder, settings.embeddings_cache_dir
    )
    if not trait_embeddings:
        return 0.0, []

    task_vec = embedder.encode([task])[0]
    scored: list[tuple[str, float]] = []
    for combined, vector in trait_embeddings.items():
        _, _, value = combined.partition("::")
        scored.append((value, cosine(task_vec, vector)))

    scored.sort(key=lambda vs: (-vs[1], vs[0]))
    best = scored[0][1]
    top = [value for value, _ in scored[:_TOP_N]]
    return best, top


def detect_gap(*, task: str, settings: Any = None) -> GapSignal | None:
    """Return a :class:`GapSignal` only on a true catalog miss, else ``None``.

    Callers should invoke this only when trait inference already found
    nothing for *task* (``not inferred.has_any()``) — that is the signal
    that the task might be a genuine gap. This function then confirms it
    with a fuzzy pass over the whole catalog before it is reported,
    preferring embedding cosine similarity when available and falling back
    to lexical word overlap otherwise.

    :param task: The natural-language task description.
    :param settings: App settings; defaults to :func:`app.config.get_settings`.
        Tolerates an incompletely configured environment (returns ``None``)
        so this can never break a resolve.
    """
    if settings is None:
        from pydantic import ValidationError

        try:
            settings = get_settings()
        except ValidationError:
            return None

    if not getattr(settings, "gap_detection_enabled", True):
        return None

    embedding_result = _embedding_recall(task, settings)
    if embedding_result is not None:
        best_score, matched = embedding_result
        threshold = getattr(settings, "gap_recall_min_score", 0.30)
        if best_score >= threshold:
            return None
        return GapSignal(
            task=task,
            best_recall_score=best_score,
            matched_traits=matched,
            reason="no-catalog-match",
        )

    best_overlap, matched = _lexical_recall(task)
    min_overlap = getattr(settings, "gap_lexical_min_overlap", 1)
    if best_overlap >= min_overlap:
        return None
    return GapSignal(
        task=task,
        best_recall_score=best_overlap,
        matched_traits=matched,
        reason="no-catalog-match",
    )
