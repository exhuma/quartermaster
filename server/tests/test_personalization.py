"""Tests for the bounded, familiarity-based ranking nudge."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import personalization


@pytest.fixture(autouse=True)
def _fake_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = [
        (
            SimpleNamespace(name="module-auth-oidc"),
            SimpleNamespace(
                domains=["auth"], languages=["python"], frameworks=["fastapi"]
            ),
        ),
        (
            SimpleNamespace(name="module-pytorch"),
            SimpleNamespace(
                domains=["ml"], languages=["python"], frameworks=["pytorch"]
            ),
        ),
    ]
    monkeypatch.setattr("app.personalization.iter_catalog", lambda: catalog)


def _candidate(name: str, score: int) -> dict:
    return {
        "name": name,
        "latest_version": "v1",
        "kit_type": "module",
        "score": score,
        "confidence": "medium",
        "reasons": [],
        "summary": "s",
    }


def test_no_profile_returns_candidates_unchanged() -> None:
    candidates = [
        _candidate("module-auth-oidc", 50),
        _candidate("module-pytorch", 70),
    ]
    result = personalization.apply_memory_nudge(candidates, None)
    assert result == candidates


def test_real_trait_match_always_outranks_familiarity_only() -> None:
    # module-auth-oidc is maximally "familiar" (every bonus dimension hits),
    # but module-pytorch's real score lead exceeds the bonus cap (8).
    profile = {
        "top_kits": ["module-auth-oidc"],
        "top_domains": ["auth"],
        "top_languages": ["python"],
        "top_frameworks": ["fastapi"],
    }
    candidates = [
        _candidate("module-auth-oidc", 50),
        _candidate("module-pytorch", 60),
    ]
    result = personalization.apply_memory_nudge(candidates, profile)
    assert [c["name"] for c in result] == ["module-pytorch", "module-auth-oidc"]


def test_familiarity_breaks_a_near_tie_within_the_cap() -> None:
    profile = {
        "top_kits": ["module-auth-oidc"],
        "top_domains": [],
        "top_languages": [],
        "top_frameworks": [],
    }
    # Score gap (3) is within the single-dimension bonus (top_kits = 3).
    candidates = [
        _candidate("module-pytorch", 53),
        _candidate("module-auth-oidc", 50),
    ]
    result = personalization.apply_memory_nudge(candidates, profile)
    assert result[0]["name"] == "module-auth-oidc"


def test_candidate_set_is_always_preserved() -> None:
    profile = {
        "top_kits": ["module-auth-oidc"],
        "top_domains": [],
        "top_languages": [],
        "top_frameworks": [],
    }
    candidates = [
        _candidate("module-auth-oidc", 50),
        _candidate("module-pytorch", 70),
    ]
    result = personalization.apply_memory_nudge(candidates, profile)
    assert {c["name"] for c in result} == {c["name"] for c in candidates}
    assert len(result) == len(candidates)


def test_bonus_components_sum_and_clamp_to_cap() -> None:
    # module-auth-oidc matches all four dimensions: 3+2+2+1 = 8 = the cap.
    profile = {
        "top_kits": ["module-auth-oidc"],
        "top_domains": ["auth"],
        "top_languages": ["python"],
        "top_frameworks": ["fastapi"],
    }
    bonus = personalization._bonus_for(
        _candidate("module-auth-oidc", 50),
        profile,
        personalization._kit_applicability_map(),
    )
    assert bonus == personalization.MEMORY_BONUS_CAP == 8


def test_empty_profile_dict_behaves_like_no_profile() -> None:
    # An empty (falsy) profile takes the same identity-passthrough path as
    # None -- input order is preserved, not re-sorted by score.
    candidates = [
        _candidate("module-auth-oidc", 50),
        _candidate("module-pytorch", 70),
    ]
    result = personalization.apply_memory_nudge(candidates, {})
    assert result == candidates


def test_profile_hint_empty_for_no_profile() -> None:
    assert personalization.profile_hint(None) == ""
    assert personalization.profile_hint({}) == ""


def test_profile_hint_empty_when_profile_has_no_entries() -> None:
    profile = {
        "top_domains": [],
        "top_kits": [],
        "top_languages": [],
        "top_frameworks": [],
    }
    assert personalization.profile_hint(profile) == ""


def test_profile_hint_mentions_languages_frameworks_and_domains() -> None:
    profile = {
        "top_domains": ["auth"],
        "top_kits": ["module-auth-oidc"],
        "top_languages": ["python"],
        "top_frameworks": ["fastapi"],
    }
    hint = personalization.profile_hint(profile)
    assert "python" in hint
    assert "fastapi" in hint
    assert "auth" in hint
    assert "advisory only" in hint.lower()


def test_profile_hint_never_mentions_kit_names() -> None:
    # Advisory context is trait-shaped only, never a specific kit
    # recommendation, so it can't be mistaken for a forced selection.
    profile = {
        "top_domains": [],
        "top_kits": ["module-super-secret-kit"],
        "top_languages": [],
        "top_frameworks": [],
    }
    assert "module-super-secret-kit" not in personalization.profile_hint(
        profile
    )
