"""
Local-embedding inference engine for ``resolve_kits``.

This is the deterministic baseline: it embeds the task text and the per-trait
pseudo-documents (and candidate sections) with a local model and ranks by
cosine similarity. It needs no network and, given a fixed model, is
reproducible. The real model is loaded lazily via ``fastembed`` (ONNX, no
torch); when the dependency or model is unavailable :func:`get_embedder`
returns ``None`` and the resolver degrades to the lexical floor.

Trait-document embeddings are cached on disk keyed by the embedding model id
and the catalog fingerprint, so editing a kit invalidates them automatically
and a warm process never re-embeds the vocabulary.
"""

from __future__ import annotations

import json
import logging
import math
import re
from pathlib import Path
from typing import Any, Protocol

from app.resolver import InferredTrait, InferredTraits
from app.traits import (
    SectionRef,
    TraitVocabulary,
    build_trait_docs,
    catalog_fingerprint,
)

logger = logging.getLogger(__name__)

_TRAIT_KEYS = ("languages", "frameworks", "capabilities", "contexts")


class Embedder(Protocol):
    """A text-embedding backend."""

    model_id: str

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...


class FastEmbedEmbedder:
    """
    Real embedder backed by ``fastembed`` (ONNX CPU, no torch).

    The model is loaded lazily on first ``encode`` so import stays cheap and
    a missing dependency surfaces only when embeddings are actually used.
    """

    def __init__(self, model_id: str, *, cache_dir: str | None = None) -> None:
        self.model_id = model_id
        self._cache_dir = cache_dir
        self._model: Any | None = None

    def _ensure_model(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding  # lazy, optional dependency

            kwargs: dict[str, Any] = {"model_name": self.model_id}
            if self._cache_dir:
                # Persist model files alongside our caches (e.g. on the data
                # volume) so they survive restarts and need no re-download.
                kwargs["cache_dir"] = self._cache_dir
            self._model = TextEmbedding(**kwargs)
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_model()
        return [list(map(float, vector)) for vector in model.embed(texts)]


def get_embedder(settings: Any) -> Embedder | None:
    """
    Return a configured embedder, or ``None`` to degrade to lexical.

    Returns ``None`` when embeddings are disabled or the dependency/model
    cannot be loaded, so the resolver never fails because of embeddings.
    """
    if not getattr(settings, "embeddings_enabled", False):
        return None
    cache_dir = getattr(settings, "embeddings_cache_dir", None)
    model_cache = str(Path(cache_dir) / "models") if cache_dir else None
    try:
        return FastEmbedEmbedder(
            settings.embeddings_model, cache_dir=model_cache
        )
    except Exception as exc:  # pragma: no cover - depends on environment
        logger.warning("embeddings unavailable, degrading: %s", exc)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    """Return cosine similarity, or 0.0 if either vector is zero-length."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _cache_path(cache_dir: Path, model_id: str, fingerprint: str) -> Path:
    safe_model = _SAFE_NAME_RE.sub("_", model_id)
    return cache_dir / f"{safe_model}-{fingerprint}.json"


def build_trait_embeddings(
    embedder: Embedder, cache_dir: Path
) -> dict[str, list[float]]:
    """
    Return ``{"category::value": vector}`` for every trait pseudo-document.

    Results are cached on disk keyed by the embedder's ``model_id`` and the
    current catalog fingerprint; a matching cache is reused without calling
    the embedder, and a stale one (any manifest/section edit) is replaced.

    :param embedder: The embedding backend.
    :param cache_dir: Directory holding the on-disk cache.
    :returns: Mapping of ``"category::value"`` to embedding vector.
    """
    fingerprint = catalog_fingerprint()
    path = _cache_path(cache_dir, embedder.model_id, fingerprint)
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            logger.warning("ignoring unreadable embedding cache: %s", exc)

    docs = build_trait_docs()
    keys = [f"{doc.category}::{doc.value}" for doc in docs]
    vectors = embedder.encode([doc.text for doc in docs])
    embeddings = dict(zip(keys, vectors, strict=True))

    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(embeddings), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:  # caching is best-effort
        logger.warning("could not write embedding cache: %s", exc)
    return embeddings


class EmbeddingTraitEngine:
    """
    Trait inference and section ranking via cosine similarity.

    Implements the resolver's ``TraitEngine`` protocol. Trait-document
    embeddings come from :func:`build_trait_embeddings` (cached); the task
    and sections are embedded per call.
    """

    name = "embedding"

    def __init__(
        self,
        embedder: Embedder,
        *,
        cache_dir: Path,
        min_score: float = 0.30,
        top_k: int = 4,
    ) -> None:
        self._embedder = embedder
        self._cache_dir = cache_dir
        self._min_score = min_score
        self._top_k = top_k

    def infer(
        self, task: str, vocab: TraitVocabulary
    ) -> InferredTraits | None:
        trait_embeddings = build_trait_embeddings(
            self._embedder, self._cache_dir
        )
        task_vec = self._embedder.encode([task])[0]

        known = vocab.flat()
        per_cat: dict[str, list[tuple[str, float]]] = {
            key: [] for key in _TRAIT_KEYS
        }
        for combined, vector in trait_embeddings.items():
            category, _, value = combined.partition("::")
            if category not in per_cat or value not in known:
                continue
            score = cosine(task_vec, vector)
            if score >= self._min_score:
                per_cat[category].append((value, score))

        selected: dict[str, list[str]] = {}
        provenance: list[InferredTrait] = []
        for key in _TRAIT_KEYS:
            ranked = sorted(per_cat[key], key=lambda vs: (-vs[1], vs[0]))
            chosen = ranked[: self._top_k]
            selected[key] = [value for value, _ in chosen]
            provenance += [
                InferredTrait(key, value, self.name) for value, _ in chosen
            ]

        return InferredTraits(
            languages=selected["languages"],
            frameworks=selected["frameworks"],
            capabilities=selected["capabilities"],
            contexts=selected["contexts"],
            provenance=provenance,
            engine=self.name,
        )

    def rank_sections(
        self, task: str, refs: list[SectionRef]
    ) -> list[tuple[SectionRef, float]]:
        if not refs:
            return []
        task_vec = self._embedder.encode([task])[0]
        vectors = self._embedder.encode([ref.text for ref in refs])
        scored: list[tuple[SectionRef, float]] = []
        for ref, vector in zip(refs, vectors, strict=True):
            score = cosine(task_vec, vector)
            # Below-threshold sections score 0.0 so the resolver drops them,
            # keeping the on-demand list lean rather than offering weak hits.
            scored.append((ref, score if score >= self._min_score else 0.0))
        scored.sort(key=lambda rs: (-rs[1], rs[0].section_id))
        return scored


__all__ = [
    "Embedder",
    "EmbeddingTraitEngine",
    "FastEmbedEmbedder",
    "build_trait_embeddings",
    "cosine",
    "get_embedder",
]
