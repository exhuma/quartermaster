"""Runtime-configurable logging setup.

Logging is configured from the environment at startup so operators can redirect
logs (disk, logstash, syslog, custom HTTP endpoints) **without rebuilding the
image**:

- ``LOG_CONFIG`` — path to a TOML file holding a standard
  :func:`logging.config.dictConfig` schema (``version = 1``, ``formatters``,
  ``handlers``, ``loggers``, ``root``). When set, it takes full control of
  logging. Set ``disable_existing_loggers = false`` so the uvicorn/app loggers
  survive. Parsed with the stdlib :mod:`tomllib` (no extra dependency).
- ``LOG_LEVEL`` — level for the default colored console output when no
  ``LOG_CONFIG`` is supplied (default ``INFO``).

The stdlib ships no JSON formatter, so :class:`JsonLinesFormatter` is provided
here for operators who want one-JSON-object-per-line on disk; reference it from
a TOML config via dictConfig's ``()`` factory key (see ``DEVELOPMENT.md``).
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from logging.config import dictConfig

from gouge.colourcli import Simple

logger = logging.getLogger(__name__)


class JsonLinesFormatter(logging.Formatter):
    """Render each log record as a single-line JSON object.

    Useful for on-disk structured logs that downstream collectors ingest one
    line at a time. Reference it from a ``LOG_CONFIG`` TOML file:

    .. code-block:: toml

        [formatters.jsonlines]
        "()" = "app.logging_config.JsonLinesFormatter"
    """

    def format(self, record: logging.LogRecord) -> str:
        """Serialize *record* to a compact single-line JSON string."""
        payload: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_default_logging() -> None:
    """Apply the colored console fallback at ``LOG_LEVEL`` (default INFO)."""
    level_name = os.environ.get("LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
    Simple.basicConfig(level=level)
    # basicConfig is a no-op once the root logger already has handlers (e.g. on
    # re-invocation), so set the level explicitly to honor LOG_LEVEL regardless.
    logging.getLogger().setLevel(level)
    # Tame the very chatty SSE keep-alive logger; only meaningful for the
    # default config (a full dictConfig is respected verbatim).
    logging.getLogger("sse_starlette").setLevel(logging.INFO)


def configure_logging() -> None:
    """Configure logging from the environment.

    Uses ``LOG_CONFIG`` (TOML → :func:`logging.config.dictConfig`) when set,
    otherwise a colored console at ``LOG_LEVEL``. A missing or unparseable
    ``LOG_CONFIG`` never aborts startup: the colored fallback is applied first
    so logs keep flowing, then the failure is logged.
    """
    config_path = os.environ.get("LOG_CONFIG", "").strip()
    if not config_path:
        _configure_default_logging()
        return

    try:
        with open(config_path, "rb") as handle:
            config = tomllib.load(handle)
        dictConfig(config)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        _configure_default_logging()
        logger.error(
            "Failed to apply LOG_CONFIG=%s (%s); using default logging.",
            config_path,
            exc,
        )
