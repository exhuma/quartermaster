"""
Tests for the local-embedding inference engine.

A deterministic fake embedder (keyword bag-of-words) stands in for the real
ONNX model so the pipeline, thresholding, and on-disk cache are exercised
with no model download or network. The real-model path is covered by a
single ``slow`` test that is skipped by default.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import embeddings, resolver
from app.embeddings import (
    EmbeddingTraitEngine,
    build_trait_embeddings,
    cosine,
    get_embedder,
)
from app.traits import SectionRef, load_vocabulary

_KEYWORDS = [
    "python",
    "fastapi",
    "typescript",
    "vue",
    "rest",
    "api",
    "frontend",
    "backend",
    "testing",
]


class FakeEmbedder:
    """Deterministic keyword-presence embedder for tests."""

    model_id = "fake-test-model"

    def __init__(self) -> None:
        self.calls = 0

    def encode(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        out: list[list[float]] = []
        for text in texts:
            lowered = text.lower()
            out.append([1.0 if kw in lowered else 0.0 for kw in _KEYWORDS])
        return out


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


def _manifest(base: Path, kit: str, data: dict) -> None:
    (base / kit / "applicability.json").write_text(
        json.dumps(data), encoding="utf-8"
    )


@pytest.fixture()
def kit_root(tmp_path: Path) -> Path:
    _write_kit_version(
        tmp_path,
        "kit-alpha",
        "v1",
        "Alpha summary.",
        [
            {
                "file": "invariant.md",
                "title": "Invariants",
                "gloss": "Core rules",
                "always_load": True,
                "body": "## Invariants\n\nLayered.\n",
            },
            {
                "file": "endpoints.md",
                "title": "REST endpoints",
                "gloss": "Add a rest api endpoint route",
                "body": "## Endpoints\n",
            },
        ],
    )
    _manifest(
        tmp_path,
        "kit-alpha",
        {
            "kit_type": "module",
            "summary": "FastAPI backend guidance for Python services.",
            "domains": ["api", "backend"],
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
            "optional_signals": ["rest"],
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


def test_cosine_basic() -> None:
    assert cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
    assert cosine([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0  # zero vector guard


def test_engine_infers_framework_from_task(tmp_path: Path) -> None:
    engine = EmbeddingTraitEngine(
        FakeEmbedder(), cache_dir=tmp_path / "emb", min_score=0.3, top_k=4
    )
    result = engine.infer("add a fastapi rest endpoint", load_vocabulary())
    assert result is not None
    assert "fastapi" in result.frameworks
    assert result.engine == "embedding"
    sources = {p.provenance for p in result.provenance}
    assert sources == {"embedding"}


def test_engine_ranks_relevant_section_first(tmp_path: Path) -> None:
    engine = EmbeddingTraitEngine(
        FakeEmbedder(), cache_dir=tmp_path / "emb", min_score=0.3, top_k=4
    )
    refs = [
        SectionRef(
            kit="k",
            version="v1",
            section_id="endpoints",
            title="REST endpoints",
            gloss="add a rest api endpoint",
            always_load=False,
            bytes=10,
            text="REST endpoints. add a rest api endpoint",
        ),
        SectionRef(
            kit="k",
            version="v1",
            section_id="testing",
            title="Testing",
            gloss="pytest fixtures",
            always_load=False,
            bytes=10,
            text="Testing. pytest fixtures",
        ),
    ]
    ranked = engine.rank_sections("add a rest api endpoint", refs)
    assert ranked[0][0].section_id == "endpoints"
    assert ranked[0][1] > ranked[1][1]


def test_build_trait_embeddings_uses_disk_cache(tmp_path: Path) -> None:
    cache = tmp_path / "emb"
    fake = FakeEmbedder()
    first = build_trait_embeddings(fake, cache)
    calls_after_first = fake.calls
    assert calls_after_first > 0
    # Second call with the same catalog reads the cache: no new encoding.
    second = build_trait_embeddings(fake, cache)
    assert fake.calls == calls_after_first
    assert set(first) == set(second)


def test_cache_invalidated_when_catalog_changes(
    tmp_path: Path, kit_root: Path
) -> None:
    cache = tmp_path / "emb"
    fake = FakeEmbedder()
    build_trait_embeddings(fake, cache)
    calls_after_first = fake.calls
    # Edit a manifest -> fingerprint changes -> embeddings recomputed.
    _manifest(
        kit_root,
        "kit-alpha",
        {
            "kit_type": "module",
            "summary": "FastAPI backend guidance for Python services. (v2)",
            "domains": ["api", "backend"],
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
            "optional_signals": ["rest"],
            "related_kits": [],
            "priority": 70,
        },
    )
    build_trait_embeddings(fake, cache)
    assert fake.calls > calls_after_first


def test_get_embedder_disabled_returns_none() -> None:
    settings = type(
        "S",
        (),
        {"embeddings_enabled": False, "embeddings_model": "x"},
    )()
    assert get_embedder(settings) is None


def test_pipeline_uses_embedding_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = EmbeddingTraitEngine(
        FakeEmbedder(), cache_dir=tmp_path / "emb", min_score=0.3, top_k=4
    )
    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [engine])
    out = resolver.resolve_kits(task="add a fastapi rest endpoint")
    assert out["engine"] == "embedding"
    assert "fastapi" in out["inferred_traits"]["frameworks"]


@pytest.mark.slow
def test_real_fastembed_model_smoke(tmp_path: Path) -> None:
    """Exercises the real ONNX model; skipped unless -m slow is requested."""
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "BAAI/bge-small-en-v1.5",
        },
    )()
    embedder = get_embedder(settings)
    if embedder is None:
        pytest.skip("fastembed not installed")
    engine = EmbeddingTraitEngine(
        embedder, cache_dir=tmp_path / "emb", min_score=0.3, top_k=4
    )
    result = engine.infer("build a fastapi rest api", load_vocabulary())
    assert result is not None
    assert "fastapi" in result.frameworks


def test_module_exposes_protocol() -> None:
    assert hasattr(embeddings, "Embedder")
