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


@pytest.fixture(autouse=True)
def _reset_embeddings_module_state():
    # get_embedder memoizes FastEmbedEmbedder instances and warm_up flips a
    # process-wide readiness flag; both are module-level state that must
    # not leak across tests.
    embeddings._reset_embedder_cache_for_tests()
    embeddings._reset_readiness_for_tests()
    yield
    embeddings._reset_embedder_cache_for_tests()
    embeddings._reset_readiness_for_tests()


def test_get_embedder_memoizes_by_model_cache_dir_and_threads(
    tmp_path: Path,
) -> None:
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_threads": 2,
        },
    )()
    first = get_embedder(settings)
    second = get_embedder(settings)
    assert first is second

    other_threads = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_threads": 4,
        },
    )()
    assert get_embedder(other_threads) is not first


def test_fastembed_embedder_forwards_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class _StubTextEmbedding:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[0.0] for _ in texts]

    import fastembed

    monkeypatch.setattr(fastembed, "TextEmbedding", _StubTextEmbedding)

    embedder = embeddings.FastEmbedEmbedder("fake-model", threads=3)
    embedder.encode(["hello"])
    assert captured["threads"] == 3


def test_warm_up_sets_readiness_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_warmup_niceness": 0,
        },
    )()

    assert embeddings.is_ready() is False
    assert embeddings.warm_up(settings) is True
    assert embeddings.is_ready() is True


def test_warm_up_leaves_readiness_flag_unset_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: None)
    assert embeddings.warm_up(object()) is False
    assert embeddings.is_ready() is False


def test_warm_up_applies_configured_niceness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)
    calls: list[int] = []
    monkeypatch.setattr(embeddings.os, "nice", calls.append)
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_warmup_niceness": 15,
        },
    )()

    embeddings.warm_up(settings)

    assert calls == [15]


def test_warm_up_tolerates_niceness_not_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)

    def _boom(_n: int) -> None:
        raise OSError("not supported on this platform")

    monkeypatch.setattr(embeddings.os, "nice", _boom)
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_warmup_niceness": 10,
        },
    )()

    # Must not raise, and warmup still completes. The failure logs at
    # WARNING (not DEBUG) so a blocked syscall — e.g. under a restrictive
    # container seccomp profile — is visible in default-level logs.
    with caplog.at_level("WARNING", logger=embeddings.logger.name):
        assert embeddings.warm_up(settings) is True
    assert embeddings.is_ready() is True
    assert any("niceness" in r.message for r in caplog.records)


def test_build_trait_embeddings_reports_progress_on_miss(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force multiple chunks even for the small fixture catalog so progress
    # is observed incrementing rather than jumping straight to "done".
    monkeypatch.setattr(embeddings, "_EMBED_PROGRESS_CHUNK", 1)
    fake = FakeEmbedder()
    snapshots: list[tuple[int, int]] = []
    original_encode = fake.encode

    def _tracking_encode(texts: list[str]) -> list[list[float]]:
        result = original_encode(texts)
        snapshots.append(embeddings.warmup_progress())
        return result

    fake.encode = _tracking_encode  # type: ignore[method-assign]

    assert embeddings.warmup_progress() == (0, 0)
    embeddings.build_trait_embeddings(fake, tmp_path / "emb")

    total = snapshots[-1][1]
    assert total > 1  # the fixture catalog yields more than one trait doc
    # Each snapshot is taken *during* a chunk's encode() call, so it reflects
    # docs completed by prior chunks, not the in-flight one.
    assert [done for done, _ in snapshots] == list(range(total))
    assert embeddings.warmup_progress() == (total, total)


def test_build_trait_embeddings_reports_full_progress_on_cache_hit(
    tmp_path: Path,
) -> None:
    cache = tmp_path / "emb"
    fake = FakeEmbedder()
    first = build_trait_embeddings(fake, cache)
    embeddings._warmup_progress.done = 0
    embeddings._warmup_progress.total = 0

    build_trait_embeddings(fake, cache)

    assert embeddings.warmup_progress() == (len(first), len(first))


def test_warmup_thread_niceness_reads_back_applied_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)
    monkeypatch.setattr(embeddings.os, "nice", lambda n: n)
    monkeypatch.setattr(embeddings.os, "getpriority", lambda _which, _who: 15)
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_warmup_niceness": 15,
        },
    )()

    assert embeddings.warmup_thread_niceness() is None
    embeddings.warm_up(settings)
    assert embeddings.warmup_thread_niceness() == 15


def test_warmup_thread_niceness_none_when_query_unsupported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)
    monkeypatch.setattr(embeddings.os, "nice", lambda n: n)

    def _boom(_which: int, _who: int) -> int:
        raise OSError("not supported")

    monkeypatch.setattr(embeddings.os, "getpriority", _boom)
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path,
            "embeddings_warmup_niceness": 10,
        },
    )()

    embeddings.warm_up(settings)
    assert embeddings.warmup_thread_niceness() is None


def test_build_trait_engines_excludes_embedding_until_warmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake = FakeEmbedder()
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path / "emb",
            "embeddings_min_score": 0.3,
            "embeddings_top_k_per_category": 4,
        },
    )()
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)

    # Warmup hasn't completed: a working embedder must not be used yet, so a
    # request in the gap falls back to the lexical floor instead of racing
    # the background warmup thread into a second, concurrent model load.
    engines = resolver._build_trait_engines()
    assert not any(e.name == "embedding" for e in engines)

    embeddings._ready_event.set()
    engines = resolver._build_trait_engines()
    assert any(e.name == "embedding" for e in engines)


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


def test_warm_up_loads_model_and_populates_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = FakeEmbedder()
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: fake)
    settings = type(
        "S",
        (),
        {
            "embeddings_enabled": True,
            "embeddings_model": "fake",
            "embeddings_cache_dir": tmp_path / "emb",
        },
    )()

    assert embeddings.warm_up(settings) is True
    # The model was exercised (vocab embed + forced load), so the in-memory
    # ONNX session is live for the first real request.
    assert fake.calls > 0
    # The trait-embedding disk cache is now warm: a later build reads it
    # without re-encoding, proving the first request pays no vocab-embed cost.
    calls_after_warm = fake.calls
    build_trait_embeddings(fake, tmp_path / "emb")
    assert fake.calls == calls_after_warm


def test_warm_up_returns_false_when_embedder_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(embeddings, "get_embedder", lambda _s: None)
    assert embeddings.warm_up(object()) is False


def test_module_exposes_protocol() -> None:
    assert hasattr(embeddings, "Embedder")
