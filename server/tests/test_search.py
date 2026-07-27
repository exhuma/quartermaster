"""Tests for :func:`app.kits.search_catalog`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.kits import search_catalog


def _write_kit_version(
    base: Path,
    kit: str,
    ver: str,
    summary: str,
    sections: list[dict],
) -> None:
    """Create ``base/<kit>/<ver>/instructions/`` with index.toml + files."""
    instr = base / kit / ver / "instructions"
    instr.mkdir(parents=True)
    lines = [f'summary = "{summary}"', ""]
    for s in sections:
        (instr / s["file"]).write_text(s["body"], encoding="utf-8")
        lines += [
            "[[sections]]",
            f'file = "{s["file"]}"',
            f'title = "{s["title"]}"',
            f'gloss = "{s.get("gloss", s["title"])}"',
            f'always_load = {"true" if s.get("always_load") else "false"}',
            "",
        ]
    (instr / "index.toml").write_text("\n".join(lines), encoding="utf-8")


def _write_manifest(base: Path, kit: str, **overrides: object) -> None:
    manifest = {
        "kit_type": "module",
        "summary": "Default summary.",
        "domains": [],
        "languages": [],
        "frameworks": [],
        "contexts": [],
        "requires": {
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        "excludes": {
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        "optional_signals": [],
        "related_kits": [],
        "priority": 50,
    }
    manifest.update(overrides)
    (base / kit / "applicability.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


@pytest.fixture()
def search_kit_root(tmp_path: Path) -> Path:
    """A kits root with two kits tailored to search-scoring scenarios."""
    _write_kit_version(
        tmp_path,
        "kit-alpha",
        "v1",
        summary="FastAPI backend guidance for Python services.",
        sections=[
            {
                "file": "overview.md",
                "title": "Overview",
                "gloss": "What this kit is",
                "body": "# Agent instructions: kit-alpha\n",
            },
            {
                "file": "tooling.md",
                "title": "Tooling",
                "gloss": "Project setup",
                "body": (
                    "## Tooling\n\n"
                    "Use the widget-frobnicator utility to sync deps.\n"
                ),
            },
        ],
    )
    _write_manifest(
        tmp_path,
        "kit-alpha",
        summary="FastAPI backend guidance for Python services.",
        domains=["api-design", "backend"],
        languages=["python"],
        frameworks=["fastapi"],
        contexts=["backend"],
        optional_signals=["rest-api", "async"],
        priority=70,
    )

    _write_kit_version(
        tmp_path,
        "kit-beta",
        "v1",
        summary="Vue frontend guidance for TypeScript apps.",
        sections=[
            {
                "file": "overview.md",
                "title": "Overview",
                "gloss": "What this kit is",
                "body": "# Agent instructions: kit-beta\n",
            },
        ],
    )
    _write_manifest(
        tmp_path,
        "kit-beta",
        summary="Vue frontend guidance for TypeScript apps.",
        domains=["frontend", "ui"],
        languages=["typescript"],
        frameworks=["vue"],
        contexts=["frontend"],
        optional_signals=["spa", "components"],
        priority=40,
    )
    return tmp_path


@pytest.fixture()
def search_kit_root_with_broken_index(search_kit_root: Path) -> Path:
    """Same catalog, but kit-beta's index.toml is unparsable."""
    index = search_kit_root / "kit-beta" / "v1" / "instructions" / "index.toml"
    index.write_text("this = [is, not, valid, toml", encoding="utf-8")
    return search_kit_root


def _patch_settings(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": root})(),
    )


def test_blank_query_returns_no_results(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("   ")
    assert result == {"query": "   ", "results": []}


def test_matches_by_kit_name(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("kit-alpha")
    names = [r["name"] for r in result["results"]]
    assert names == ["kit-alpha"]


def test_matches_by_applicability_field(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("fastapi")
    names = [r["name"] for r in result["results"]]
    assert names == ["kit-alpha"]
    alpha = result["results"][0]
    assert any(f.startswith("frameworks:fastapi") for f in alpha["matched_fields"])


def test_matches_by_section_body_only(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "widget-frobnicator" appears only in kit-alpha's tooling.md body — not
    # in its name, summary, or any applicability field.
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("widget-frobnicator")
    assert len(result["results"]) == 1
    alpha = result["results"][0]
    assert alpha["name"] == "kit-alpha"
    assert len(alpha["sections"]) == 1
    section = alpha["sections"][0]
    assert section["id"] == "tooling"
    assert "widget-frobnicator" in section["snippet"]


def test_score_ordering_prefers_stronger_matches(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "frontend" appears in kit-beta's domains AND contexts, but only as a
    # weaker single optional_signals-less match for kit-alpha (not at all,
    # actually) — assert kit-beta ranks first and alone.
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("frontend")
    names = [r["name"] for r in result["results"]]
    assert names == ["kit-beta"]


def test_broken_kit_excluded_from_search(
    search_kit_root_with_broken_index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, search_kit_root_with_broken_index)
    result = search_catalog("vue")
    names = [r["name"] for r in result["results"]]
    assert "kit-beta" not in names


def test_limit_caps_results(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("guidance", limit=1)
    assert len(result["results"]) == 1


def test_no_match_returns_empty_results(
    search_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_settings(monkeypatch, search_kit_root)
    result = search_catalog("nonexistent-phrase-xyz")
    assert result["results"] == []
