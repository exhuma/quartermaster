"""
Tests for trait vocabulary, pseudo-document, and section-ref derivation.

These back the server-side ``resolve_kits`` pipeline: they confirm the
vocabulary and the text used to match a task against traits/sections are
derived deterministically from the kit manifests.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import traits
from app.kits import KitApplicability, KitInfo, iter_catalog


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


def _write_manifest(base: Path, kit: str, manifest: dict) -> None:
    (base / kit / "applicability.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


@pytest.fixture()
def kit_root(tmp_path: Path) -> Path:
    """Create a temporary kits root with two kits (python/fastapi, ts/vue)."""
    _write_kit_version(
        tmp_path,
        "kit-alpha",
        "v1",
        summary="Alpha summary.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Architecture invariants",
                "gloss": "Non-negotiables for the FastAPI layering",
                "always_load": True,
                "body": "## Invariants\n\nKeep it layered.\n",
            },
            {
                "file": "endpoints.md",
                "title": "REST endpoints",
                "gloss": "How to add a REST API route",
                "body": "## Endpoints\n\nAdd routers.\n",
            },
        ],
    )
    _write_kit_version(
        tmp_path,
        "kit-beta",
        "v1",
        summary="Beta summary.",
        sections=[
            {
                "file": "overview.md",
                "title": "Overview",
                "gloss": "What this kit is",
                "body": "# kit-beta\n",
            }
        ],
    )
    _write_manifest(
        tmp_path,
        "kit-alpha",
        {
            "kit_type": "module",
            "summary": "FastAPI backend guidance for Python services.",
            "domains": ["api-design", "backend"],
            "languages": ["python"],
            "frameworks": ["fastapi"],
            "contexts": ["backend"],
            "requires": {
                "languages": ["python"],
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
            "optional_signals": ["rest-api", "async"],
            "related_kits": ["kit-beta"],
            "priority": 70,
        },
    )
    _write_manifest(
        tmp_path,
        "kit-beta",
        {
            "kit_type": "module",
            "summary": "Vue frontend guidance for TypeScript apps.",
            "domains": ["frontend", "ui"],
            "languages": ["typescript"],
            "frameworks": ["vue"],
            "contexts": ["frontend"],
            "requires": {
                "languages": [],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
            "excludes": {
                "languages": ["python"],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
            "optional_signals": ["spa", "components"],
            "related_kits": [],
            "priority": 40,
        },
    )
    return tmp_path


@pytest.fixture(autouse=True)
def _use_kit_root(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point the kit loaders at the temporary catalog."""
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )


def test_iter_catalog_returns_kit_info_and_applicability() -> None:
    entries = iter_catalog()
    by_name = {info.name: (info, app) for info, app in entries}
    assert set(by_name) == {"kit-alpha", "kit-beta"}
    info, app = by_name["kit-alpha"]
    assert isinstance(info, KitInfo)
    assert isinstance(app, KitApplicability)
    assert app.frameworks == ["fastapi"]


def test_load_vocabulary_aggregates_all_categories() -> None:
    vocab = traits.load_vocabulary()
    assert set(vocab.languages) == {"python", "typescript"}
    assert set(vocab.frameworks) == {"fastapi", "vue"}
    # capabilities = domains + optional_signals
    assert {"api-design", "backend", "rest-api", "frontend"} <= set(
        vocab.capabilities
    )
    assert set(vocab.contexts) == {"backend", "frontend"}


def test_vocabulary_flat_and_by_category() -> None:
    vocab = traits.load_vocabulary()
    assert "fastapi" in vocab.flat()
    assert "python" in vocab.flat()
    by_cat = vocab.all_by_category()
    assert by_cat["frameworks"] == vocab.frameworks
    assert set(by_cat) == {
        "languages",
        "frameworks",
        "capabilities",
        "contexts",
    }


def test_build_trait_docs_pseudo_document_aggregates_kit_text() -> None:
    docs = traits.build_trait_docs()
    by_key = {(d.category, d.value): d for d in docs}
    fastapi_doc = by_key[("frameworks", "fastapi")]
    # The pseudo-doc embeds the declaring kit's summary and domains so the
    # token "fastapi" matches task text about FastAPI services, not the bare
    # word alone.
    text = fastapi_doc.text.lower()
    assert "fastapi" in text
    assert "python services" in text
    assert "api-design" in text


def test_build_trait_docs_token_with_no_extra_text_is_just_the_token() -> None:
    docs = traits.build_trait_docs()
    by_key = {(d.category, d.value): d for d in docs}
    # "vue" is declared only by kit-beta; ensure a doc exists and includes
    # the token even if aggregation is sparse.
    vue_doc = by_key[("frameworks", "vue")]
    assert "vue" in vue_doc.text.lower()


def test_build_section_refs_carries_ranking_text() -> None:
    refs = traits.build_section_refs(["kit-alpha"])
    by_id = {r.section_id: r for r in refs}
    assert set(by_id) == {"invariant", "endpoints"}
    endpoints = by_id["endpoints"]
    assert endpoints.kit == "kit-alpha"
    assert endpoints.always_load is False
    assert by_id["invariant"].always_load is True
    # ranking text contains title + gloss
    assert "rest" in endpoints.text.lower()
    assert "route" in endpoints.text.lower()


def test_catalog_fingerprint_is_stable_and_changes_on_edit(
    kit_root: Path,
) -> None:
    first = traits.catalog_fingerprint()
    assert first == traits.catalog_fingerprint()
    # mutate a manifest -> fingerprint must change
    _write_manifest(
        kit_root,
        "kit-beta",
        {
            "kit_type": "module",
            "summary": "Vue frontend guidance for TypeScript apps. (edited)",
            "domains": ["frontend", "ui"],
            "languages": ["typescript"],
            "frameworks": ["vue"],
            "contexts": ["frontend"],
            "requires": {
                "languages": [],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
            "excludes": {
                "languages": ["python"],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
            "optional_signals": ["spa", "components"],
            "related_kits": [],
            "priority": 40,
        },
    )
    assert traits.catalog_fingerprint() != first
