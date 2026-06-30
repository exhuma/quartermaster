"""
Optional, pluggable LLM inference for ``resolve_kits``.

When configured, an LLM does the fuzzy task→traits step (the highest-value
inference) constrained to the server's closed trait vocabulary and returning
strict JSON. Two backends sit behind one protocol: an OpenAI-compatible HTTP
endpoint (covering Ollama/vLLM/llama.cpp and cloud) and the Anthropic
Messages API. The factory :func:`get_llm_backend` returns ``None`` when the
LLM is unconfigured, and every failure mode (network, timeout, malformed
output, out-of-vocabulary) makes the engine return ``None`` so the resolver
falls back to embeddings, then to the lexical floor — the LLM can never break
resolution.

Section ranking is delegated to a cheaper deterministic ranker (embeddings or
lexical), so a resolve costs at most one LLM call.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

import httpx

from app.resolver import (
    InferredTrait,
    InferredTraits,
    LexicalTraitEngine,
    SectionRef,
    TraitEngine,
    TraitVocabulary,
)

logger = logging.getLogger(__name__)

_TRAIT_KEYS = ("languages", "frameworks", "capabilities", "contexts")
_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
_MAX_TOKENS = 512


class LLMError(Exception):
    """Raised for any LLM call failure (network, timeout, bad output)."""


class LLMBackend(Protocol):
    """A JSON-returning LLM backend."""

    name: str

    def complete_json(
        self, *, system: str, user: str, timeout: float
    ) -> dict:
        """Return the model's response parsed as a JSON object."""
        ...


def _coerce_json_object(raw: Any) -> dict:
    """Parse *raw* (str or object) into a JSON object or raise LLMError."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise LLMError(f"model did not return valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise LLMError("model JSON was not an object")
    return raw


class OpenAICompatBackend:
    """OpenAI-compatible ``/chat/completions`` backend."""

    name = "openai"

    def __init__(
        self, *, base_url: str, model: str, api_key: str | None
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key

    def complete_json(
        self, *, system: str, user: str, timeout: float
    ) -> dict:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = httpx.request(
                "POST",
                self._url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected LLM response shape: {exc}") from exc
        return _coerce_json_object(content)


class AnthropicBackend:
    """Anthropic Messages API backend."""

    name = "anthropic"

    def __init__(self, *, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def complete_json(
        self, *, system: str, user: str, timeout: float
    ) -> dict:
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "temperature": 0,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        try:
            response = httpx.request(
                "POST",
                _ANTHROPIC_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            text = response.json()["content"][0]["text"]
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"unexpected LLM response shape: {exc}") from exc
        return _coerce_json_object(text)


def get_llm_backend(settings: Any) -> LLMBackend | None:
    """
    Return a configured LLM backend, or ``None`` when the LLM is disabled.

    OpenAI-compatible needs ``llm_base_url`` + ``llm_model``; Anthropic needs
    ``llm_api_key`` + ``llm_model``. Anything else (including an unknown
    provider) disables the LLM layer.
    """
    provider = (getattr(settings, "llm_provider", None) or "").strip().lower()
    if provider == "openai":
        if settings.llm_base_url and settings.llm_model:
            return OpenAICompatBackend(
                base_url=settings.llm_base_url,
                model=settings.llm_model,
                api_key=settings.llm_api_key,
            )
        return None
    if provider == "anthropic":
        if settings.llm_api_key and settings.llm_model:
            return AnthropicBackend(
                api_key=settings.llm_api_key, model=settings.llm_model
            )
        return None
    return None


_SYSTEM_PROMPT = (
    "You map a software development task onto a CLOSED vocabulary of project "
    "traits. Respond with a single JSON object whose keys are 'languages', "
    "'frameworks', 'capabilities' and 'contexts', each a list of strings. "
    "Use ONLY values from the provided allowed lists; omit a category if "
    "none apply. Output JSON only, no prose."
)


def _build_user_prompt(task: str, vocab: TraitVocabulary) -> str:
    lines = [f"Task:\n{task}", "", "Allowed values:"]
    for key, values in vocab.all_by_category().items():
        lines.append(f"- {key}: {', '.join(sorted(values)) or '(none)'}")
    return "\n".join(lines)


def _constrain_to_vocab(
    data: Any, vocab: TraitVocabulary, *, engine: str
) -> InferredTraits | None:
    """
    Constrain a model's raw trait object to the closed vocabulary.

    Shared by the LLM and sampling engines: the model is never trusted, so
    each emitted value must match a known vocabulary token (case-insensitive)
    and is de-duplicated. Returns ``None`` when *data* is not an object or
    nothing in-vocabulary survives, so the caller falls through to the next
    engine.

    :param data: The model's parsed JSON (expected to be an object).
    :param vocab: The closed trait vocabulary to constrain against.
    :param engine: Provenance/engine label to stamp on the result.
    :returns: The constrained :class:`InferredTraits`, or ``None``.
    """
    if not isinstance(data, dict):
        return None

    known_by_cat = vocab.all_by_category()
    selected: dict[str, list[str]] = {}
    provenance: list[InferredTrait] = []
    for key in _TRAIT_KEYS:
        raw = data.get(key, [])
        if not isinstance(raw, list):
            raw = []
        allowed = set(known_by_cat[key])
        kept: list[str] = []
        for value in raw:
            token = str(value).strip().lower()
            if token in allowed and token not in kept:
                kept.append(token)
        selected[key] = kept
        provenance += [InferredTrait(key, v, engine) for v in kept]

    result = InferredTraits(
        languages=selected["languages"],
        frameworks=selected["frameworks"],
        capabilities=selected["capabilities"],
        contexts=selected["contexts"],
        provenance=provenance,
        engine=engine,
    )
    return result if result.has_any() else None


class LLMTraitEngine:
    """
    Trait inference via an LLM, with deterministic section ranking.

    Implements the resolver's ``TraitEngine`` protocol. Returns ``None`` from
    :meth:`infer` on any failure or when nothing in-vocabulary survives, so
    the resolver falls through to the next engine.
    """

    name = "llm"

    def __init__(
        self,
        backend: LLMBackend,
        *,
        timeout: float,
        section_ranker: TraitEngine | None = None,
    ) -> None:
        self._backend = backend
        self._timeout = timeout
        self._section_ranker: Any = section_ranker or LexicalTraitEngine()

    def infer(
        self, task: str, vocab: TraitVocabulary
    ) -> InferredTraits | None:
        user = _build_user_prompt(task, vocab)
        try:
            data = self._backend.complete_json(
                system=_SYSTEM_PROMPT, user=user, timeout=self._timeout
            )
        except LLMError as exc:
            logger.warning("LLM inference failed: %s", exc)
            return None

        return _constrain_to_vocab(data, vocab, engine=self.name)

    def rank_sections(
        self, task: str, refs: list[SectionRef]
    ) -> list[tuple[SectionRef, float]]:
        return self._section_ranker.rank_sections(task, refs)


__all__ = [
    "AnthropicBackend",
    "LLMBackend",
    "LLMError",
    "LLMTraitEngine",
    "OpenAICompatBackend",
    "get_llm_backend",
]
