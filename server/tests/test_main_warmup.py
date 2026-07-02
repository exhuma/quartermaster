"""Tests for the startup embedding warmup wired into the app lifespan.

The warmup moves the fastembed model load + trait-vocabulary embedding off the
first ``resolve_kits`` request (where it otherwise causes a cold-start timeout)
and onto pod startup. Like the metrics-store init, it is best-effort: a failure
must never block the app from starting.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app import main


def test_warm_embeddings_invokes_warm_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(embeddings_enabled=True)
    monkeypatch.setattr(main, "get_settings", lambda: settings)
    seen: list[object] = []
    monkeypatch.setattr(
        "app.embeddings.warm_up", lambda s: seen.append(s) or True
    )

    main._warm_embeddings()

    assert seen == [settings]


def test_warm_embeddings_swallows_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace())

    def _boom(_s: object) -> bool:
        raise RuntimeError("model download hung")

    monkeypatch.setattr("app.embeddings.warm_up", _boom)

    # Must not raise: a warmup failure cannot block startup.
    main._warm_embeddings()
