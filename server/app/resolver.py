"""
One-shot kit resolution: task description in, recommendation + content out.

``resolve_kits`` collapses the client-side discovery dance (list traits →
select → explain → outline → get) into a single server-side call. It infers
the project traits a task touches, feeds them to the existing deterministic
scorer :func:`app.kits.select_kits_v2` (unchanged), then assembles a hybrid
response: the recommendation, the ``always_load`` sections inlined, and the
other relevant section ids left for the client to fetch on demand.

Trait inference runs a fallback chain — optional LLM, then local embeddings,
then a lexical floor that is always available, so the tool never hard-fails.
This module wires the chain and the assembly; the LLM and embedding engines
live in :mod:`app.llm` and :mod:`app.embeddings` and are appended ahead of
the floor by :func:`_build_trait_engines` when configured.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app import telemetry
from app.kits import read_kit, select_kits_v2
from app.tokens import count_tokens, estimate_tokens_from_bytes
from app.traits import (
    SectionRef,
    TraitVocabulary,
    build_section_refs,
    load_vocabulary,
)

logger = logging.getLogger(__name__)

_TRAIT_KEYS = ("languages", "frameworks", "capabilities", "contexts")


@dataclass(frozen=True)
class InferredTrait:
    """One inferred trait and where it came from."""

    category: str
    value: str
    provenance: str  # "llm" | "embedding" | "lexical"


@dataclass(frozen=True)
class InferredTraits:
    """The four inferred trait lists plus provenance and engine label."""

    languages: list[str]
    frameworks: list[str]
    capabilities: list[str]
    contexts: list[str]
    provenance: list[InferredTrait]
    engine: str

    def has_any(self) -> bool:
        """Return whether any trait was inferred in any category."""
        return bool(
            self.languages
            or self.frameworks
            or self.capabilities
            or self.contexts
        )


class TraitEngine(Protocol):
    """An inference engine: task → traits, and task → section ranking."""

    name: str

    def infer(
        self, task: str, vocab: TraitVocabulary
    ) -> InferredTraits | None:
        """Infer traits, or return ``None`` to fall through to the next."""
        ...

    def rank_sections(
        self, task: str, refs: list[SectionRef]
    ) -> list[tuple[SectionRef, float]]:
        """Rank sections by task relevance, highest first."""
        ...


# ---------------------------------------------------------------------------
# Lexical engine (the always-available floor)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    """Return *text* as space-delimited lowercase word tokens, padded."""
    return " " + " ".join(_WORD_RE.findall(text.lower())) + " "


def _phrase_present(token: str, normalized_task: str) -> bool:
    """
    Return whether *token* appears in an already-normalized task string.

    Matches the token as a contiguous word phrase (so ``rest-api`` matches
    "rest api"); for multi-word tokens it also matches when every part
    appears somewhere as a whole word.
    """
    parts = _WORD_RE.findall(token.lower())
    if not parts:
        return False
    phrase = " " + " ".join(parts) + " "
    if phrase in normalized_task:
        return True
    if len(parts) > 1:
        return all(f" {part} " in normalized_task for part in parts)
    return False


class LexicalTraitEngine:
    """
    Deterministic lexical matcher: the floor that never fails.

    Trait inference matches each vocabulary token against the task text;
    section ranking scores word overlap between the task and each
    section's title + gloss.
    """

    name = "lexical"

    def infer(
        self, task: str, vocab: TraitVocabulary
    ) -> InferredTraits:
        normalized = _normalize(task)
        per_cat: dict[str, list[str]] = {k: [] for k in _TRAIT_KEYS}
        provenance: list[InferredTrait] = []
        for category, values in vocab.all_by_category().items():
            for token in values:
                if _phrase_present(token, normalized):
                    per_cat[category].append(token)
                    provenance.append(
                        InferredTrait(category, token, self.name)
                    )
        return InferredTraits(
            languages=per_cat["languages"],
            frameworks=per_cat["frameworks"],
            capabilities=per_cat["capabilities"],
            contexts=per_cat["contexts"],
            provenance=provenance,
            engine=self.name,
        )

    def rank_sections(
        self, task: str, refs: list[SectionRef]
    ) -> list[tuple[SectionRef, float]]:
        task_words = set(_normalize(task).split())
        scored: list[tuple[SectionRef, float]] = []
        for ref in refs:
            words = set(_normalize(ref.text).split())
            overlap = len(task_words & words)
            scored.append((ref, float(overlap)))
        scored.sort(key=lambda rs: (-rs[1], rs[0].section_id))
        return scored


def _build_trait_engines() -> list[TraitEngine]:
    """
    Return the optional inference engines, highest priority first.

    The lexical floor is appended separately in :func:`resolve_kits` and is
    always present. The embedding engine is added when an embedder is
    available (and the LLM engine, when configured, is prepended ahead of
    it). Kept as a module-level function so tests can swap it to force a
    particular engine. Imports are local to avoid an import cycle with
    :mod:`app.embeddings`, which imports the trait types defined here.

    Settings access is tolerant: when configuration is incomplete (e.g.
    during test collection) no optional engine is built and the lexical
    floor handles resolution.
    """
    # Local imports break the resolver <-> embeddings/llm import cycles.
    from pydantic import ValidationError

    from app.config import get_settings
    from app.embeddings import EmbeddingTraitEngine, get_embedder
    from app.llm import LLMTraitEngine, get_llm_backend

    try:
        settings = get_settings()
    except ValidationError:
        return []

    # Build the deterministic embedding engine first: it doubles as the LLM
    # engine's section ranker (so an LLM resolve still ranks sections by
    # embedding similarity at no extra LLM cost), and it is the fallback when
    # the LLM yields nothing.
    embedding_engine: EmbeddingTraitEngine | None = None
    embedder = get_embedder(settings)
    if embedder is not None:
        embedding_engine = EmbeddingTraitEngine(
            embedder,
            cache_dir=settings.embeddings_cache_dir,
            min_score=settings.embeddings_min_score,
            top_k=settings.embeddings_top_k_per_category,
        )

    engines: list[TraitEngine] = []
    backend = get_llm_backend(settings)
    if backend is not None:
        engines.append(
            LLMTraitEngine(
                backend,
                timeout=settings.llm_timeout_seconds,
                section_ranker=embedding_engine,
            )
        )
    if embedding_engine is not None:
        engines.append(embedding_engine)
    return engines


def _infer(
    task: str, vocab: TraitVocabulary
) -> tuple[TraitEngine, InferredTraits]:
    """
    Run the fallback chain and return the winning engine and its result.

    The first engine that yields any trait wins. The lexical floor is tried
    last and always returns a (possibly empty) result, so a winner always
    exists.
    """
    engines: list[TraitEngine] = [*_build_trait_engines(), LexicalTraitEngine()]
    chosen_engine: TraitEngine | None = None
    chosen: InferredTraits | None = None
    for engine in engines:
        try:
            result = engine.infer(task, vocab)
        except Exception as exc:  # an engine must never break resolution
            logger.warning("trait engine %r failed: %s", engine.name, exc)
            continue
        if result is None:
            continue
        chosen_engine, chosen = engine, result
        if result.has_any():
            break
    # The lexical floor guarantees a non-None result.
    assert chosen_engine is not None and chosen is not None
    return chosen_engine, chosen


def _section_descriptor(ref: SectionRef, relevance: float) -> dict[str, Any]:
    """Return the public per-section descriptor."""
    return {
        "id": ref.section_id,
        "title": ref.title,
        "gloss": ref.gloss,
        "relevance": round(float(relevance), 3),
        "always_load": ref.always_load,
    }


def resolve_kits(
    *,
    task: str,
    broaden: bool = False,
    limit: int = 8,
    max_sections_per_kit: int = 8,
) -> dict[str, Any]:
    """
    Resolve a natural-language task to recommended kits and content.

    :param task: Natural-language description of the work to be done.
    :param broaden: Forwarded to :func:`select_kits_v2` to widen recall.
    :param limit: Maximum number of candidate kits to return.
    :param max_sections_per_kit: Cap on non-``always_load`` sections offered
        for on-demand fetch per kit.
    :returns: The hybrid response described in this module's docstring.
    :raises ValueError: If *task* is empty.
    """
    task = (task or "").strip()
    if not task:
        raise ValueError("task must not be empty")

    with telemetry.span("resolve.infer") as infer_span:
        vocab = load_vocabulary()
        engine, inferred = _infer(task, vocab)
        telemetry.set_attrs(
            infer_span,
            {
                "engine": inferred.engine,
                "trait.count": len(inferred.provenance),
            },
        )

    with telemetry.span("resolve.select") as select_span:
        selection = select_kits_v2(
            languages=inferred.languages,
            frameworks=inferred.frameworks,
            capabilities=inferred.capabilities,
            contexts=inferred.contexts,
            broaden=broaden,
            limit=limit,
        )
        telemetry.set_attrs(
            select_span,
            {
                "candidates": len(selection["candidates"]),
                "confidence": selection["confidence"],
                "coverage": selection["coverage"],
            },
        )

    kits_out: list[dict[str, Any]] = []
    total_delivered = 0
    total_offered = 0
    with telemetry.span("resolve.assemble") as assemble_span:
        for candidate in selection["candidates"]:
            name = candidate["name"]
            refs = build_section_refs([name])
            version = refs[0].version if refs else candidate["latest_version"]
            always = [r for r in refs if r.always_load]
            rest = [r for r in refs if not r.always_load]

            ranked = engine.rank_sections(task, rest)
            relevance_by_id = {r.section_id: score for r, score in ranked}
            relevant = [
                (r, score) for r, score in ranked if score > 0
            ][:max_sections_per_kit]

            descriptors = [
                _section_descriptor(r, relevance_by_id.get(r.section_id, 0.0))
                for r in always
            ]
            descriptors += [
                _section_descriptor(r, score) for r, score in relevant
            ]

            always_ids = [r.section_id for r in always]
            markdown = (
                read_kit(name, version, sections=always_ids)
                if always_ids
                else ""
            )

            offered_ids = [r.section_id for r, _ in relevant]
            delivered_tokens = count_tokens(markdown) if markdown else 0
            # Offered sections are not read here (they are fetched on demand),
            # so size them from the known byte counts rather than re-reading.
            offered_tokens = sum(
                estimate_tokens_from_bytes(r.bytes) for r, _ in relevant
            )
            total_delivered += delivered_tokens
            total_offered += offered_tokens
            telemetry.record_kit_delivery(
                kit=name,
                disposition="inlined",
                tokens=delivered_tokens,
                section_ids=always_ids,
            )
            if offered_ids:
                telemetry.record_kit_delivery(
                    kit=name,
                    disposition="offered",
                    tokens=offered_tokens,
                    section_ids=offered_ids,
                )

            kits_out.append(
                {
                    "name": name,
                    "version": version,
                    "score": candidate["score"],
                    "confidence": candidate["confidence"],
                    "reasons": candidate["reasons"],
                    "summary": candidate["summary"],
                    "sections": descriptors,
                    "always_load_markdown": markdown,
                    "fetch_on_demand": offered_ids,
                }
            )
        telemetry.set_attrs(
            assemble_span,
            {
                "kits": len(kits_out),
                "delivered_tokens": total_delivered,
                "offered_tokens": total_offered,
            },
        )

    telemetry.record_resolve(
        engine=inferred.engine,
        confidence=selection["confidence"],
        coverage=selection["coverage"],
        broadening_recommended=selection["broadening_recommended"],
        delivered_tokens=total_delivered,
        offered_tokens=total_offered,
        traits={
            "languages": inferred.languages,
            "frameworks": inferred.frameworks,
            "capabilities": inferred.capabilities,
            "contexts": inferred.contexts,
        },
    )

    return {
        "engine": inferred.engine,
        "inferred_traits": {
            "languages": inferred.languages,
            "frameworks": inferred.frameworks,
            "capabilities": inferred.capabilities,
            "contexts": inferred.contexts,
            "provenance": [
                {
                    "category": p.category,
                    "value": p.value,
                    "source": p.provenance,
                }
                for p in inferred.provenance
            ],
        },
        "confidence": selection["confidence"],
        "coverage": selection["coverage"],
        "broadening_recommended": selection["broadening_recommended"],
        "kits": kits_out,
        "warnings": selection["warnings"],
    }
