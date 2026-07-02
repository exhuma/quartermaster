"""Tests for catalog-recall gap detection (app.gap)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import gap


def _write_kit_version(
    base: Path, kit: str, ver: str, summary: str, sections: list[dict]
) -> None:
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
    _write_kit_version(
        tmp_path,
        "kit-alpha",
        "v1",
        summary="Alpha summary.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Architecture invariants",
                "gloss": "Non-negotiables for FastAPI layering",
                "always_load": True,
                "body": "## Invariants\n\nKeep it layered.\n",
            },
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
            "optional_signals": ["rest-api", "async"],
            "related_kits": [],
            "priority": 70,
        },
    )
    return tmp_path


@pytest.fixture(autouse=True)
def _use_kit_root(kit_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )


def _settings(
    *,
    gap_detection_enabled: bool = True,
    embeddings_enabled: bool = False,
    gap_recall_min_score: float = 0.30,
    gap_lexical_min_overlap: int = 1,
) -> SimpleNamespace:
    return SimpleNamespace(
        gap_detection_enabled=gap_detection_enabled,
        embeddings_enabled=embeddings_enabled,
        embeddings_cache_dir=Path("/tmp/does-not-matter"),
        gap_recall_min_score=gap_recall_min_score,
        gap_lexical_min_overlap=gap_lexical_min_overlap,
    )


def test_true_gap_via_lexical_floor() -> None:
    # No word in this task overlaps python/fastapi/backend/api-design/
    # rest-api/async — a genuine catalog miss.
    signal = gap.detect_gap(
        task="train a pytorch model on GPUs for image classification",
        settings=_settings(),
    )
    assert signal is not None
    assert signal.reason == "no-catalog-match"


def test_false_positive_guard_lexical() -> None:
    # "fastapi" and "backend" both appear in the catalog vocabulary.
    signal = gap.detect_gap(
        task="add a fastapi backend endpoint", settings=_settings()
    )
    assert signal is None


def test_disabled_flag_always_returns_none() -> None:
    signal = gap.detect_gap(
        task="train a pytorch model on GPUs",
        settings=_settings(gap_detection_enabled=False),
    )
    assert signal is None


def test_defaults_to_app_settings_when_none_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.gap.get_settings", lambda: _settings())
    signal = gap.detect_gap(task="train a pytorch model on GPUs")
    assert signal is not None


def test_embedding_path_true_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubEmbedder:
        model_id = "stub"

        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        "app.embeddings.get_embedder", lambda settings: _StubEmbedder()
    )
    monkeypatch.setattr(
        "app.embeddings.build_trait_embeddings",
        lambda embedder, cache_dir: {"languages::python": [0.0, 1.0]},
    )
    signal = gap.detect_gap(
        task="anything", settings=_settings(embeddings_enabled=True)
    )
    assert signal is not None
    assert signal.reason == "no-catalog-match"


def test_embedding_path_false_positive_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _StubEmbedder:
        model_id = "stub"

        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(
        "app.embeddings.get_embedder", lambda settings: _StubEmbedder()
    )
    monkeypatch.setattr(
        "app.embeddings.build_trait_embeddings",
        lambda embedder, cache_dir: {"languages::python": [1.0, 0.0]},
    )
    signal = gap.detect_gap(
        task="python project", settings=_settings(embeddings_enabled=True)
    )
    assert signal is None
