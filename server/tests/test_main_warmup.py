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


def test_warm_embeddings_announces_start_before_completion(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A "starting" line must precede the completion line, so the container log
    # marks the wait rather than only announcing it after it finishes.
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr("app.embeddings.warm_up", lambda _s: True)

    with caplog.at_level("INFO", logger=main.logger.name):
        main._warm_embeddings()

    messages = [r.message for r in caplog.records]
    start = next(i for i, m in enumerate(messages) if "warming embedding" in m)
    done = next(i for i, m in enumerate(messages) if "warmed at startup" in m)
    assert start < done
