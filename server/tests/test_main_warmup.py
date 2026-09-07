"""Tests for the startup embedding warmup wired into the app lifespan.

The warmup moves the fastembed model load + trait-vocabulary embedding off the
first ``resolve_kits`` request (where it otherwise causes a cold-start timeout)
and onto a dedicated background thread started at startup. Like the
metrics-store init, it is best-effort: a failure must never block the app from
starting, and — unlike the metrics-store init — startup itself must never wait
for it to finish either.
"""

from __future__ import annotations

import threading
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


def test_start_embeddings_warmup_returns_without_waiting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    started = threading.Event()

    def _blocking_warm_up(_s: object) -> bool:
        started.set()
        release.wait(timeout=5)
        return True

    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr("app.embeddings.warm_up", _blocking_warm_up)

    thread = main._start_embeddings_warmup()
    try:
        # The call itself must not block on warm_up finishing.
        assert started.wait(timeout=5)
        assert thread.is_alive()
    finally:
        release.set()
        thread.join(timeout=5)


def test_start_embeddings_warmup_uses_a_dedicated_daemon_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace())
    monkeypatch.setattr("app.embeddings.warm_up", lambda _s: True)

    thread = main._start_embeddings_warmup()
    try:
        assert thread.daemon is True
        assert thread.name == "embeddings-warmup"
        assert thread is not threading.current_thread()
    finally:
        thread.join(timeout=5)
