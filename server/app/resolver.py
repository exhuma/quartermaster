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

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app import telemetry
from app.clarify import detect_clarification
from app.config import get_settings
from app.gap import detect_gap
from app.identity import current_sub
from app.kits import read_kit, resolve_effective_version, select_kits_v2
from app.notifications import gap_tools_enabled
from app.observability import local_store
from app.personalization import apply_memory_nudge
from app.storage import user_memory
from app.tokens import count_tokens, estimate_tokens_from_bytes
from app.traits import (
    SectionRef,
    TraitVocabulary,
    build_section_refs,
    load_vocabulary,
)

logger = logging.getLogger(__name__)

_TRAIT_KEYS = ("languages", "frameworks", "capabilities", "contexts")
_MAX_GAP_TITLE_LEN = 80


@dataclass(frozen=True)
class InferredTrait:
    """One inferred trait and where it came from."""

    category: str
    value: str
    provenance: str  # "sampling" | "llm" | "embedding" | "lexical"


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


def build_ranker() -> TraitEngine:
    """
    Return the deterministic section ranker for a sampled/pre-inferred resolve.

    When trait inference is supplied externally (e.g. by MCP sampling in the
    tool wrapper), the resolver still needs to rank sections. Prefer the
    embedding engine when available; otherwise the always-present lexical
    floor. Mirrors the ranker the LLM engine uses, so an externally-inferred
    resolve ranks sections exactly like the configured-LLM path.

    :returns: A :class:`TraitEngine` exposing ``rank_sections``.
    """
    for engine in _build_trait_engines():
        # The embedding engine (if built) is the deterministic ranker; the LLM
        # engine delegates ranking to it anyway, so either is acceptable.
        if engine.name == "embedding":
            return engine
    return LexicalTraitEngine()


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


def _suggest_gap_title(task: str) -> str:
    """Return a short issue-title candidate derived from *task*."""
    collapsed = " ".join(task.split())
    if len(collapsed) <= _MAX_GAP_TITLE_LEN:
        return collapsed
    return collapsed[: _MAX_GAP_TITLE_LEN - 1].rstrip() + "…"


def _gap_block(signal: Any) -> dict[str, Any] | None:
    """Return the public ``gap`` response field, or ``None`` when no gap."""
    if signal is None:
        return None
    return {
        "detected": True,
        "reason": signal.reason,
        "suggested_title": _suggest_gap_title(signal.task),
        "suggested_summary": signal.task,
        "discovered_traits": signal.matched_traits,
        "recall_score": round(signal.best_recall_score, 3),
        "file_hint": (
            "Call request_clarification_or_addition to file this gap."
            if gap_tools_enabled()
            else "No issue backend configured."
        ),
    }


# Human-facing presentation for the clarification block. Kept here (not in
# app/clarify.py) so the detector stays pure structured data.
_CLARIFY_QUESTION_TEXT = {
    "languages": "Which programming language is this project written in?",
    "frameworks": "Which application/framework does this project use?",
    "capabilities": "Which capability best describes this work?",
    "contexts": "What project context does this apply to?",
}
_CLARIFY_HINT = {
    "languages": (
        "Inspect the repo: *.csproj/*.sln → csharp; pyproject.toml/setup.py/"
        "requirements.txt → python; package.json → javascript (tsconfig.json "
        "present → typescript); go.mod → go; Cargo.toml → rust; pom.xml/"
        "build.gradle → java."
    ),
    "frameworks": (
        "Inspect dependency manifests: fastapi/django/flask in "
        "pyproject.toml; react/vue/express in package.json; the framework "
        "packages give it away."
    ),
    "capabilities": (
        "Infer from the task and nearby code which capability is being added."
    ),
    "contexts": (
        "Infer from the repo layout (backend/frontend/docs/infra directories)."
    ),
}
_CLARIFY_HOW_TO_ANSWER = (
    "A pivotal project trait is missing, so kits cannot be confidently "
    "chosen. Answer each question YOURSELF from the repository before asking "
    "the human: inspect the files named in each question's `hint`, pick the "
    "matching "
    "`option`, then re-call resolve_kits with the answer folded into `task` "
    "(e.g. append '(python; pyproject.toml present)'). Only surface a question "
    "to the human when repo inspection is genuinely ambiguous."
)


def _clarification_block(signal: Any) -> dict[str, Any] | None:
    """Return the public ``clarification`` response field, or ``None``."""
    if signal is None:
        return None
    return {
        "needed": True,
        "reason": signal.reason,
        "how_to_answer": _CLARIFY_HOW_TO_ANSWER,
        "questions": [
            {
                "category": question.category,
                "question": _CLARIFY_QUESTION_TEXT.get(
                    question.category, f"Which {question.category}?"
                ),
                "why": question.why,
                "options": question.options,
                "hint": _CLARIFY_HINT.get(question.category, ""),
                "blocking_kits": question.blocking_kits,
            }
            for question in signal.questions
        ],
    }


def _maybe_apply_memory_nudge(
    candidates: list[dict[str, Any]], subject: str | None
) -> list[dict[str, Any]]:
    """Re-sort *candidates* using the caller's memory profile, when available.

    A no-op (returns *candidates* unchanged) unless all of: the caller is
    authenticated, settings are valid and ``user_memory_enabled``, and the
    local metrics store is initialised. Tolerant of any failure — memory
    personalization must never break a resolve.
    """
    if not subject:
        return candidates
    try:
        settings = get_settings()
    except Exception:  # noqa: BLE001 - e.g. ValidationError during test/startup
        return candidates
    if not getattr(settings, "user_memory_enabled", True):
        return candidates
    store = local_store.get_store()
    if store is None:
        return candidates
    try:
        profile = user_memory.get_or_build(
            settings.user_memory_store_path,
            subject,
            store,
            ttl_seconds=settings.user_memory_ttl_seconds,
            half_life_days=settings.user_memory_half_life_days,
            caps=user_memory.ProfileCaps(
                domains=settings.user_memory_top_domains,
                kits=settings.user_memory_top_kits,
                languages=settings.user_memory_top_languages,
                frameworks=settings.user_memory_top_frameworks,
            ),
            now=time.time(),
        )
        return apply_memory_nudge(candidates, profile)
    except Exception:  # noqa: BLE001
        logger.warning(
            "memory nudge failed, using unnudged candidates", exc_info=True
        )
        return candidates


def resolve_kits(
    *,
    task: str,
    broaden: bool = False,
    limit: int = 8,
    max_sections_per_kit: int = 8,
    pre_inferred: InferredTraits | None = None,
    section_ranker: TraitEngine | None = None,
    pins: dict[str, str] | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """
    Resolve a natural-language task to recommended kits and content.

    :param task: Natural-language description of the work to be done.
    :param broaden: Forwarded to :func:`select_kits_v2` to widen recall.
    :param limit: Maximum number of candidate kits to return.
    :param max_sections_per_kit: Cap on non-``always_load`` sections offered
        for on-demand fetch per kit.
    :param pre_inferred: Externally-inferred traits (e.g. from MCP sampling in
        the tool wrapper). When supplied, the internal inference chain is
        skipped and these traits drive selection.
    :param section_ranker: Section ranker to use with *pre_inferred*. Defaults
        to :func:`build_ranker` (embedding engine or lexical floor). Ignored
        when *pre_inferred* is ``None``.
    :param pins: Per-kit major-version pins the agent read from the repo's
        ``.quartermaster.toml``. A pinned kit is inlined at its pinned major;
        an unpinned multi-version kit is inlined at its earliest major with a
        ``version_advisory`` attached.
    :param project_id: Optional stable repo label from ``.quartermaster.toml``,
        recorded with adoption telemetry only.
    :returns: The hybrid response described in this module's docstring.
    :raises ValueError: If *task* is empty.
    """
    pins = pins or {}
    task = (task or "").strip()
    if not task:
        raise ValueError("task must not be empty")

    with telemetry.span("resolve.infer") as infer_span:
        vocab = load_vocabulary()
        if pre_inferred is not None:
            inferred = pre_inferred
            ranker = section_ranker or build_ranker()
        else:
            ranker, inferred = _infer(task, vocab)
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

    # Bounded, familiarity-based re-sort of the already-selected candidates —
    # never changes which kits were selected, only their order (see
    # app.personalization for the anti-tunnel-vision bound).
    selection["candidates"] = _maybe_apply_memory_nudge(
        selection["candidates"], current_sub()
    )

    # Trait inference found nothing at all for this task: confirm with a
    # catalog-recall pass before treating it as a genuine gap (a real match
    # here means the miss was in wording/inference, not catalog coverage).
    gap_signal = None
    clarify_signal = None
    if not inferred.has_any():
        gap_signal = detect_gap(task=task)
        if gap_signal is not None:
            telemetry.record_gap_detected()
    else:
        # Inference found *something* but a pivotal required trait may still be
        # missing (e.g. "add a database" with no language). Ask the agent to
        # resolve it from repo inspection and re-resolve. Mutually exclusive
        # with the gap path above by the has_any() guards.
        clarify_signal = detect_clarification(
            selection=selection,
            inferred={
                "languages": inferred.languages,
                "frameworks": inferred.frameworks,
                "capabilities": inferred.capabilities,
                "contexts": inferred.contexts,
            },
            vocab=vocab,
        )

    kits_out: list[dict[str, Any]] = []
    total_delivered = 0
    total_offered = 0
    # Per-kit deliveries for the OTEL-independent local store, recorded once
    # after the loop so the "delivered together" set is kept for co-occurrence.
    local_deliveries: list[tuple[str, str, int]] = []
    with telemetry.span("resolve.assemble") as assemble_span:
        for candidate in selection["candidates"]:
            name = candidate["name"]
            # Serve the pinned major (or the conservative default for an
            # unpinned multi-version kit) and describe/rank that version's
            # sections, not the latest.
            version, advisory = resolve_effective_version(
                name, pin=pins.get(name)
            )

            # A policy kit still missing a required trait: surface it as
            # pending mandatory policy but deliver no body — its project type
            # is unknown, so its content might be the wrong policy. The
            # companion clarification block asks for the trait that unlocks it.
            if candidate.get("policy") and candidate.get("needs"):
                kit_out = {
                    "name": name,
                    "version": version,
                    "score": candidate["score"],
                    "confidence": candidate["confidence"],
                    "reasons": candidate["reasons"],
                    "summary": candidate["summary"],
                    "sections": [],
                    "always_load_markdown": "",
                    "fetch_on_demand": [],
                    "policy": True,
                    "policy_pending": True,
                }
                if advisory is not None:
                    kit_out["version_advisory"] = advisory
                kits_out.append(kit_out)
                continue

            refs = build_section_refs([name], version)
            always = [r for r in refs if r.always_load]
            rest = [r for r in refs if not r.always_load]

            ranked = ranker.rank_sections(task, rest)
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
            local_deliveries.append((name, "inlined", delivered_tokens))
            if offered_ids:
                telemetry.record_kit_delivery(
                    kit=name,
                    disposition="offered",
                    tokens=offered_tokens,
                    section_ids=offered_ids,
                )
                local_deliveries.append((name, "offered", offered_tokens))

            kit_out = {
                "name": name,
                "version": version,
                "score": candidate["score"],
                "confidence": candidate["confidence"],
                "reasons": candidate["reasons"],
                "summary": candidate["summary"],
                "sections": descriptors,
                "always_load_markdown": markdown,
                "fetch_on_demand": offered_ids,
                "policy": bool(candidate.get("policy")),
            }
            if advisory is not None:
                kit_out["version_advisory"] = advisory
            kits_out.append(kit_out)

            local_store.record_kit_version_use(
                kit=name,
                version=version,
                pinned=name in pins and advisory is None,
                advisory_shown=advisory is not None,
                subject=current_sub(),
                project_id=project_id,
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
    # Mirror into the OTEL-independent local store so the in-app Metrics
    # dashboard has data even when OTLP export is broken/unconfigured. Also
    # attributes the resolve to the authenticated caller (when present) and
    # persists the inferred traits, feeding per-user memory derivation (see
    # app.storage.user_memory) — never a delivery-blocking dependency.
    local_store.record_resolve(
        engine=inferred.engine,
        confidence=selection["confidence"],
        coverage=selection["coverage"],
        broadening=selection["broadening_recommended"],
        deliveries=local_deliveries,
        delivered_tokens=total_delivered,
        offered_tokens=total_offered,
        subject=current_sub(),
        project_id=project_id,
        traits_json=json.dumps(
            {
                "languages": inferred.languages,
                "frameworks": inferred.frameworks,
                "capabilities": inferred.capabilities,
                "contexts": inferred.contexts,
            }
        ),
    )
    local_store.maybe_snapshot_catalog()

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
        "gap": _gap_block(gap_signal),
        "clarification": _clarification_block(clarify_signal),
    }
