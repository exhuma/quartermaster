"""Tests for the token-counting helpers (app/tokens.py)."""

from __future__ import annotations

import app.tokens as tokens


def test_count_tokens_positive_and_stable() -> None:
    """Counting the same text twice yields the same positive value."""
    text = "Add OIDC authentication to the FastAPI backend."
    first = tokens.count_tokens(text)
    second = tokens.count_tokens(text)
    assert first == second
    assert first > 0


def test_count_tokens_empty_is_zero() -> None:
    """Empty text counts as zero tokens."""
    assert tokens.count_tokens("") == 0


def test_count_tokens_falls_back_when_tiktoken_unavailable(
    monkeypatch,
) -> None:
    """A failed tiktoken load degrades to a bytes/4 estimate, not an error."""
    # Force the lazy encoder to report unavailable.
    monkeypatch.setattr(tokens, "_ENCODER", None)
    monkeypatch.setattr(tokens, "_ENCODER_TRIED", False)
    monkeypatch.setattr(
        tokens, "_load_encoder", lambda: None
    )
    text = "x" * 40  # 40 bytes -> 10 estimated tokens
    assert tokens.count_tokens(text) == 10


def test_count_tokens_fallback_minimum_one() -> None:
    """Short non-empty text never estimates to zero in the fallback path."""
    monkeypatch_text = "a"
    # bytes/4 of 1 byte == 0, but a non-empty string must be at least 1.
    assert tokens.estimate_tokens_from_bytes(1) == 1
    assert tokens.estimate_tokens_from_bytes(len(monkeypatch_text)) == 1


def test_estimate_tokens_from_bytes_zero() -> None:
    """Zero bytes estimate to zero tokens."""
    assert tokens.estimate_tokens_from_bytes(0) == 0
