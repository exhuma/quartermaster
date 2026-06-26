"""Tests for runtime-configurable logging."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from app.logging_config import JsonLinesFormatter, configure_logging


def _make_record(**kwargs: object) -> logging.LogRecord:
    defaults: dict = {
        "name": "app.sample",
        "level": logging.INFO,
        "pathname": __file__,
        "lineno": 1,
        "msg": "hello %s",
        "args": ("world",),
        "exc_info": None,
    }
    defaults.update(kwargs)
    return logging.LogRecord(**defaults)  # type: ignore[arg-type]


def test_json_lines_formatter_is_single_line_json() -> None:
    line = JsonLinesFormatter().format(_make_record())
    assert "\n" not in line
    payload = json.loads(line)
    assert payload["level"] == "INFO"
    assert payload["logger"] == "app.sample"
    assert payload["message"] == "hello world"
    assert "ts" in payload


def test_json_lines_formatter_includes_exception() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        import sys

        record = _make_record(level=logging.ERROR, exc_info=sys.exc_info())
    payload = json.loads(JsonLinesFormatter().format(record))
    assert "exc" in payload
    assert "RuntimeError: boom" in payload["exc"]


def test_log_config_toml_is_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "logging.toml"
    config.write_text(
        "\n".join(
            [
                "version = 1",
                "disable_existing_loggers = false",
                "",
                "[formatters.plain]",
                'format = "%(message)s"',
                "",
                "[handlers.console]",
                'class = "logging.StreamHandler"',
                'formatter = "plain"',
                "",
                '[loggers."app.logtest.sample"]',
                'level = "ERROR"',
                'handlers = ["console"]',
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("QM_LOG_CONFIG", str(config))

    configure_logging()

    assert logging.getLogger("app.logtest.sample").level == logging.ERROR


def test_fallback_uses_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("QM_LOG_CONFIG", raising=False)
    monkeypatch.setenv("QM_LOG_LEVEL", "WARNING")

    configure_logging()

    assert logging.getLogger().level == logging.WARNING


def test_bad_log_config_falls_back_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QM_LOG_CONFIG", str(tmp_path / "does-not-exist.toml"))
    monkeypatch.setenv("QM_LOG_LEVEL", "ERROR")

    # Must not raise even though the config file is missing.
    configure_logging()

    assert logging.getLogger().level == logging.ERROR
