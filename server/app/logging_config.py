"""Runtime-configurable logging setup.

Logging is configured from the environment at startup so operators can redirect
logs (disk, logstash, syslog, custom HTTP endpoints) **without rebuilding the
image**:

- ``QM_LOG_CONFIG`` — path to a TOML file holding a standard
  :func:`logging.config.dictConfig` schema (``version = 1``, ``formatters``,
  ``handlers``, ``loggers``, ``root``). When set, it takes full control of
  logging. Set ``disable_existing_loggers = false`` so the uvicorn/app loggers
  survive. Parsed with the stdlib :mod:`tomllib` (no extra dependency).
- ``QM_LOG_LEVEL`` — level for the default colored console output when no
  ``QM_LOG_CONFIG`` is supplied (default ``INFO``).

The stdlib ships no JSON formatter, so :class:`JsonLinesFormatter` is provided
here for operators who want one-JSON-object-per-line on disk; reference it from
a TOML config via dictConfig's ``()`` factory key (see ``DEVELOPMENT.md``).
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from contextvars import ContextVar
from logging.config import dictConfig

from gouge.colourcli import Simple

logger = logging.getLogger(__name__)

# Per-request correlation ID (module-http-middleware-hardening). Propagated via
# a contextvar — not a function parameter — so every log record emitted during
# a request shares the same ID. The request-logging middleware sets it on the
# way in and clears it on the way out (all code paths).
_correlation_id: ContextVar[str | None] = ContextVar(
    "correlation_id", default=None
)


def set_correlation_id(cid: str) -> None:
    """Bind *cid* as the current request's correlation ID."""
    _correlation_id.set(cid)


def get_correlation_id() -> str | None:
    """Return the current correlation ID, or ``None`` outside a request."""
    return _correlation_id.get()


def clear_correlation_id() -> None:
    """Clear the correlation ID so it never leaks into the next request."""
    _correlation_id.set(None)


class CorrelationIdFilter(logging.Filter):
    """Stamp every log record with the current correlation ID.

    Attached to the root handlers so any record — from any logger active
    during a request — carries ``correlation_id`` (``"-"`` when unset).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = get_correlation_id() or "-"
        return True


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
            "cid": getattr(record, "correlation_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _configure_default_logging() -> None:
    """Apply the colored console fallback at ``LOG_LEVEL`` (default INFO)."""
    level_name = os.environ.get("QM_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, None)
    if not isinstance(level, int):
        level = logging.INFO
    Simple.basicConfig(level=level)
    # basicConfig is a no-op once the root logger already has handlers (e.g. on
    # re-invocation), so set the level explicitly to honor LOG_LEVEL regardless.
    root = logging.getLogger()
    root.setLevel(level)
    # Stamp the correlation ID onto every record passing through the root
    # handlers (idempotent — never add the filter twice).
    for handler in root.handlers:
        if not any(
            isinstance(f, CorrelationIdFilter) for f in handler.filters
        ):
            handler.addFilter(CorrelationIdFilter())
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
    config_path = os.environ.get("QM_LOG_CONFIG", "").strip()
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
            "Failed to apply QM_LOG_CONFIG=%s (%s); using default logging.",
            config_path,
            exc,
        )
