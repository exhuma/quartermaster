"""
Token-size estimation for delivered kit content.

The observability layer measures "how much content the MCP delivers" in
estimated tokens rather than bytes, because the token budget is what actually
constrains a client's context window. We use ``tiktoken``'s ``cl100k_base``
encoding (the GPT-3.5/4 BPE, a good cross-model proxy) for delivered Markdown,
and a cheap ``bytes / 4`` estimate where the body is not in hand (the
``fetch_on_demand`` sections, whose size is known only as a byte count) or when
``tiktoken`` is unavailable.

``tiktoken`` is part of the optional ``telemetry`` extra. When it is missing —
or its BPE vocabulary cannot be loaded (e.g. an air-gapped host without the
file pre-seeded under ``TIKTOKEN_CACHE_DIR``) — the module degrades to the
byte estimate and warns exactly once, so the server keeps working and metrics
keep flowing with slightly coarser numbers.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The encoding name is fixed so cached counts are comparable over time.
_ENCODING_NAME = "cl100k_base"

# Lazy, process-wide encoder handle. ``_ENCODER_TRIED`` guards the one-time
# load attempt (and the one-time warning) independently of the result, so a
# genuine ``None`` encoder is not re-attempted on every call.
_ENCODER: Any = None
_ENCODER_TRIED: bool = False


def _load_encoder() -> Any:
    """
    Return a ``tiktoken`` encoder, or ``None`` if it cannot be loaded.

    Separated from :func:`count_tokens` so tests can monkeypatch the load
    outcome without touching the public API.

    :returns: A tiktoken ``Encoding`` instance, or ``None``.
    """
    try:
        import tiktoken
    except ImportError:
        logger.warning(
            "tiktoken not installed (telemetry extra); token sizes fall "
            "back to a bytes/4 estimate."
        )
        return None
    try:
        return tiktoken.get_encoding(_ENCODING_NAME)
    except Exception as exc:  # noqa: BLE001 - any load failure degrades
        logger.warning(
            "tiktoken %r vocabulary unavailable (%s); token sizes fall "
            "back to a bytes/4 estimate. Pre-seed TIKTOKEN_CACHE_DIR for "
            "offline use.",
            _ENCODING_NAME,
            exc,
        )
        return None


def _encoder() -> Any:
    """Return the cached encoder, attempting a one-time lazy load."""
    global _ENCODER, _ENCODER_TRIED
    if not _ENCODER_TRIED:
        _ENCODER = _load_encoder()
        _ENCODER_TRIED = True
    return _ENCODER


def estimate_tokens_from_bytes(n_bytes: int) -> int:
    """
    Estimate token count from a UTF-8 byte size.

    Uses the rule-of-thumb ``~4 bytes per token`` for English prose. A
    non-empty body never estimates to zero.

    :param n_bytes: Body size in bytes.
    :returns: Estimated token count (``0`` only for an empty body).
    """
    if n_bytes <= 0:
        return 0
    return max(1, n_bytes // 4)


def count_tokens(text: str) -> int:
    """
    Return the estimated token count of *text*.

    Uses ``tiktoken``'s ``cl100k_base`` encoding when available, otherwise a
    ``bytes / 4`` estimate. Empty text is always zero tokens.

    :param text: The Markdown (or any UTF-8) content delivered to a client.
    :returns: Token count.
    """
    if not text:
        return 0
    enc = _encoder()
    if enc is None:
        return estimate_tokens_from_bytes(len(text.encode("utf-8")))
    return len(enc.encode(text))
