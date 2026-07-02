"""
MCP-sampling trait inference for ``resolve_kits``.

When the connecting client supports MCP *sampling*, the server can borrow the
client's own LLM to do the fuzzy task→traits step — no ``QM_LLM_PROVIDER``
configuration, no extra API cost. This is the *preferred* inference engine;
when sampling is unavailable or fails for any reason, the resolver falls back
to the configured HTTP LLM, then embeddings, then the lexical floor.

The engine reuses the LLM layer's prompt builders and the shared
vocabulary-constraining helper, so the sampling and HTTP-LLM paths produce
identical, vocabulary-safe output. Every failure mode returns ``None`` so the
engine can never break resolution.

Unlike the synchronous ``TraitEngine`` chain in :mod:`app.resolver`, this
engine is **async** and needs the request-scoped FastMCP ``Context`` (only the
tool wrapper has it). It is therefore driven from :mod:`app.main`, not wired
into ``_build_trait_engines``.
"""

from __future__ import annotations

import logging
from typing import Any

import mcp.types as mcp_types

from app.llm import (
    _SYSTEM_PROMPT,
    _build_user_prompt,
    _coerce_json_object,
)
from app.resolver import InferredTraits
from app.traits import TraitVocabulary

logger = logging.getLogger(__name__)


def _supports(ctx: Any, capability: mcp_types.ClientCapabilities) -> bool:
    """Return whether the connected client advertises *capability*.

    Defensive: any failure reaching the session (e.g. no active request
    context) is treated as "unsupported" rather than propagated.
    """
    try:
        return bool(ctx.session.check_client_capability(capability))
    except Exception as exc:  # capability probing must never break a resolve
        logger.debug("client capability probe failed: %s", exc)
        return False


def client_supports_sampling(ctx: Any) -> bool:
    """Return whether the client can service ``ctx.sample`` requests."""
    return _supports(
        ctx,
        mcp_types.ClientCapabilities(sampling=mcp_types.SamplingCapability()),
    )


def client_supports_elicitation(ctx: Any) -> bool:
    """Return whether the client can service ``ctx.elicit`` requests."""
    return _supports(
        ctx,
        mcp_types.ClientCapabilities(
            elicitation=mcp_types.ElicitationCapability()
        ),
    )


class SamplingTraitEngine:
    """
    Trait inference via MCP sampling (the connecting client's own LLM).

    Mirrors :class:`app.llm.LLMTraitEngine`'s contract: returns ``None`` on any
    failure or when nothing in-vocabulary survives, so the caller falls through
    to the next engine. Section ranking is *not* provided here — the resolver
    ranks sections with the deterministic embedding/lexical ranker.
    """

    name = "sampling"

    async def infer_async(
        self, task: str, vocab: TraitVocabulary, ctx: Any, *, hint: str = ""
    ) -> InferredTraits | None:
        """
        Infer traits by sampling the client's model, constrained to *vocab*.

        :param task: Natural-language task description.
        :param vocab: The closed trait vocabulary to constrain output to.
        :param ctx: The FastMCP request ``Context`` exposing ``sample``.
        :param hint: Optional advisory context (e.g. from
            :func:`app.personalization.profile_hint`) appended to the
            prompt. Purely informational — never expands *vocab*.
        :returns: Constrained :class:`InferredTraits`, or ``None`` on any
            failure / empty result.
        """
        from app.llm import _constrain_to_vocab

        user = _build_user_prompt(task, vocab)
        if hint:
            user = f"{user}\n\n{hint}"
        try:
            result = await ctx.sample(
                user, system_prompt=_SYSTEM_PROMPT, temperature=0
            )
            data = _coerce_json_object(result.text)
        except Exception as exc:  # sampling must never break resolution
            logger.warning("sampling inference failed: %s", exc)
            return None
        return _constrain_to_vocab(data, vocab, engine=self.name)


__all__ = [
    "SamplingTraitEngine",
    "client_supports_elicitation",
    "client_supports_sampling",
]
