"""
OpenTelemetry metrics + traces for Quartermaster.

This module is the single place that knows about OpenTelemetry. It builds the
providers, declares every instrument, and exposes small, defensive recording
helpers that the rest of the app calls. Telemetry must never break a request:
every public helper swallows its own errors and degrades to a no-op.

**What it measures** (see ``docs/observability.md`` for the full reference and
KPI recipes). The headline question is *how much content does the MCP deliver*,
and whether that stays flat per domain as the catalog grows:

- ``qm.catalog.*`` observable gauges — catalog mass per ``domain`` (kits,
  sections, total tokens, always-load tokens).
- ``qm.resolve.delivered_tokens`` / ``qm.resolve.offered_tokens`` histograms —
  per-call inlined vs on-demand size.
- ``qm.kit.*`` / ``qm.section.*`` counters — which kits/sections get delivered.
- ``qm.resolve.{calls,engine,confidence,coverage,broadening_recommended}`` and
  ``qm.trait.matched`` — selection health.
- ``qm.tool.{calls,duration}`` — per-tool latency (every MCP tool).

**Privacy**: no task text is ever recorded. Trait *values*, kit names and
section ids all come from the catalog vocabulary, not from client input.

**Configuration**: OTLP push is driven by the standard ``OTEL_*`` env vars read
by the SDK directly; the Prometheus pull endpoint is gated by
``QM_METRICS_PROMETHEUS_ENABLED``. With nothing configured, metrics use a no-op
meter and traces a no-op tracer — the instrumentation code still runs but emits
nothing. The whole layer is inert when the optional ``telemetry`` extra (and
thus OpenTelemetry) is not installed.
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.tokens import count_tokens, estimate_tokens_from_bytes
from app.version import app_version

logger = logging.getLogger(__name__)

try:
    from opentelemetry import metrics, trace

    # The logs signal lives under ``_logs`` (note the underscore) — unlike
    # metrics/traces it is not yet declared stable, so OTel keeps it in a
    # private-namespaced module as a "this API may still change" marker. These
    # are the documented public symbols (listed in ``opentelemetry._logs.
    # __all__``); there is no non-underscore alias to import instead. If a
    # future OTel release graduates logs, this import moves — the surrounding
    # ImportError guard degrades telemetry to inert rather than crashing.
    from opentelemetry._logs import (
        set_logger_provider as _set_logger_provider,
    )
    from opentelemetry.metrics import Observation
    from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
    from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    _OTEL_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    _OTEL_AVAILABLE = False
    logger.info(
        "OpenTelemetry not installed (telemetry extra); metrics, traces "
        "and logs are inert."
    )


# ---------------------------------------------------------------------------
# Module state (instruments + provider handles + caches)
# ---------------------------------------------------------------------------

_initialized: bool = False
_section_level: bool = False
_prometheus_enabled: bool = False
# Track whether we have actually installed each global provider. A reader-less
# init (no exporters configured) sets nothing, so a later init that *does* have
# exporters can still install the real provider (OTEL only honours the first
# successful set_*_provider call per process).
_meter_provider_set: bool = False
_tracer_provider_set: bool = False
_logger_provider_set: bool = False

_meter: Any = None
_tracer: Any = None
_instr_meter: Any = None  # identity of the meter instruments were built from

# Counters / histograms (created in _create_instruments).
_tool_calls: Any = None
_tool_duration: Any = None
_resolve_calls: Any = None
_resolve_engine: Any = None
_resolve_confidence: Any = None
_resolve_coverage: Any = None
_resolve_broadening: Any = None
_resolve_delivered_tokens: Any = None
_resolve_offered_tokens: Any = None
_kit_deliveries: Any = None
_kit_delivered_tokens: Any = None
_section_deliveries: Any = None
_trait_matched: Any = None
_gap_requested: Any = None

# Fingerprint-keyed catalog stats cache and a kit -> domains cache.
_stats_cache: tuple[str, dict[str, _DomainStats]] | None = None
_domains_cache: dict[str, list[str]] | None = None

# Passive OTLP export health, read by ``/healthz``. One entry per OTLP signal
# whose exporter is installed; the value records the outcome of the SDK's most
# recent *real* export (the batch/periodic processors call ``export`` on their
# own schedule — the health probe itself sends nothing). A key's presence means
# an OTLP exporter exists for that signal; ``ok`` is ``None`` until the first
# export attempt.
_export_state: dict[str, _ExportState] = {}


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


def init_telemetry(
    settings: Any,
    *,
    meter_provider: Any = None,
    tracer_provider: Any = None,
) -> None:
    """
    Configure metrics, traces, and logs. Idempotent and safe to call repeatedly.

    In production (no providers passed) this builds and globally registers a
    ``MeterProvider``, ``TracerProvider``, and ``LoggerProvider`` exactly once,
    driven by *settings* and the standard ``OTEL_*`` env vars. The
    ``LoggerProvider`` also installs a ``LoggingHandler`` on the root logger so
    all ``logging.getLogger(...)`` calls flow to OTLP alongside traces. Tests
    pass ``meter_provider`` / ``tracer_provider`` (e.g. backed by in-memory
    readers/exporters) to capture output without touching global state.

    :param settings: Application settings (reads the ``metrics_*`` toggles).
    :param meter_provider: Optional injected meter provider (tests).
    :param tracer_provider: Optional injected tracer provider (tests).
    """
    global _meter, _tracer, _initialized, _section_level
    if not _OTEL_AVAILABLE:
        return
    _section_level = bool(getattr(settings, "metrics_section_level", False))

    injected = meter_provider is not None or tracer_provider is not None
    if injected:
        _meter = (
            meter_provider.get_meter("quartermaster")
            if meter_provider is not None
            else metrics.get_meter("quartermaster")
        )
        _tracer = (
            tracer_provider.get_tracer("quartermaster")
            if tracer_provider is not None
            else trace.get_tracer("quartermaster")
        )
    else:
        _ensure_global_providers(settings)
        _meter = metrics.get_meter("quartermaster")
        _tracer = trace.get_tracer("quartermaster")

    _create_instruments(_meter)
    _initialized = True


def _ensure_global_providers(settings: Any) -> None:
    """Install the global providers (production path).

    Each provider is installed at most once, but a reader-less attempt leaves
    the slot open so a later, exporter-configured init can still install it.
    """
    global _meter_provider_set, _tracer_provider_set, _logger_provider_set
    if not _meter_provider_set:
        meter_provider = _build_meter_provider(settings)
        if meter_provider is not None:
            metrics.set_meter_provider(meter_provider)
            _meter_provider_set = True
    if not _tracer_provider_set:
        tracer_provider = _build_tracer_provider(settings)
        if tracer_provider is not None:
            trace.set_tracer_provider(tracer_provider)
            _tracer_provider_set = True
    if not _logger_provider_set:
        logger_provider = _build_logger_provider(settings)
        if logger_provider is not None:
            _set_logger_provider(logger_provider)
            handler = LoggingHandler(logger_provider=logger_provider)
            logging.getLogger().addHandler(handler)
            _logger_provider_set = True
    active = [
        s
        for s, flag in [
            ("metrics", _meter_provider_set),
            ("traces", _tracer_provider_set),
            ("logs", _logger_provider_set),
        ]
        if flag
    ]
    inactive = [
        s
        for s, flag in [
            ("metrics", _meter_provider_set),
            ("traces", _tracer_provider_set),
            ("logs", _logger_provider_set),
        ]
        if not flag
    ]
    if active:
        logger.info("OTLP signals active: %s", ", ".join(active))
    if inactive:
        logger.info(
            "OTLP signals inactive (no endpoint configured): %s",
            ", ".join(inactive),
        )


@dataclass
class _ExportState:
    """Most recent OTLP export outcome for one signal.

    ``ok`` is ``None`` until the first export is attempted, then ``True`` /
    ``False`` for the latest attempt. ``at`` is its wall-clock time.
    """

    ok: bool | None = None
    at: float | None = None


class _ResultRecordingExporter:
    """Wrap an OTLP exporter to record the outcome of every export.

    The SDK's batch/periodic processors call ``export`` on their own schedule;
    we intercept the return value (and any exception) so ``/healthz`` can report
    whether real telemetry is currently reaching the collector — the probe
    itself never sends anything. All other attributes (``shutdown``,
    ``force_flush``, the metric exporter's ``_preferred_*`` knobs the reader
    reads at construction) delegate transparently to the wrapped exporter.
    """

    def __init__(self, signal: str, exporter: Any) -> None:
        self._signal = signal
        self._exporter = exporter

    def export(self, *args: Any, **kwargs: Any) -> Any:
        """Delegate the export, recording success/failure either way."""
        success = False
        try:
            result = self._exporter.export(*args, **kwargs)
            success = getattr(result, "name", None) == "SUCCESS"
            return result
        finally:
            _record_export_result(self._signal, success)

    def __getattr__(self, name: str) -> Any:
        # Reached only for attributes not set on the wrapper itself; guard the
        # backing field to avoid recursion before __init__ assigns it.
        if name == "_exporter":
            raise AttributeError(name)
        return getattr(self._exporter, name)


def _wrap_exporter(signal: str, exporter: Any) -> _ResultRecordingExporter:
    """Register *signal* as OTLP-configured and wrap its exporter."""
    _export_state[signal] = _ExportState()
    return _ResultRecordingExporter(signal, exporter)


def _record_export_result(signal: str, success: bool) -> None:
    """Record the outcome of one real export (defensive; never raises)."""
    state = _export_state.get(signal)
    if state is None:
        return
    state.ok = success
    state.at = time.time()


def export_health() -> list[dict[str, Any]]:
    """Return passive OTLP export health, one entry per configured signal.

    Each entry is ``{"signal": str, "ok": bool | None, "age_seconds": float |
    None}``; ``ok is None`` means no export has happened yet. Returns an empty
    list when no OTLP exporter is configured. Consumed by ``app.health``.
    """
    now = time.time()
    return [
        {
            "signal": signal,
            "ok": state.ok,
            "age_seconds": (
                None if state.at is None else max(0.0, now - state.at)
            ),
        }
        for signal, state in _export_state.items()
    ]


def _build_meter_provider(settings: Any) -> Any:
    """Return a ``MeterProvider`` with the configured readers, or ``None``."""
    global _prometheus_enabled
    readers: list[Any] = []
    if getattr(settings, "metrics_prometheus_enabled", False):
        try:
            from opentelemetry.exporter.prometheus import (
                PrometheusMetricReader,
            )

            readers.append(PrometheusMetricReader())
            _prometheus_enabled = True
        except Exception:  # noqa: BLE001 - missing exporter degrades
            logger.warning(
                "Prometheus exporter unavailable; /metrics will not serve."
            )
    if _otlp_metrics_configured():
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (  # noqa: E501
                OTLPMetricExporter,
            )
            from opentelemetry.sdk.metrics.export import (
                PeriodicExportingMetricReader,
            )

            exporter = _wrap_exporter("metrics", OTLPMetricExporter())
            readers.append(PeriodicExportingMetricReader(exporter))
            logger.info(
                "OTLP metrics exporter configured, endpoint: %s",
                _effective_endpoint("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT"),
            )
        except Exception:  # noqa: BLE001
            logger.warning("OTLP metric exporter setup failed", exc_info=True)
    if not readers:
        return None
    return MeterProvider(resource=_resource(), metric_readers=readers)


def _build_tracer_provider(settings: Any) -> Any:
    """Return a ``TracerProvider`` exporting via OTLP, or ``None``."""
    if not _otlp_traces_configured():
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )

        provider = TracerProvider(resource=_resource())
        provider.add_span_processor(
            BatchSpanProcessor(_wrap_exporter("traces", OTLPSpanExporter()))
        )
        logger.info(
            "OTLP traces exporter configured, endpoint: %s",
            _effective_endpoint("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"),
        )
        return provider
    except Exception:  # noqa: BLE001
        logger.warning("OTLP span exporter setup failed", exc_info=True)
        return None


def _build_logger_provider(settings: Any) -> Any:
    """Return a ``LoggerProvider`` exporting via OTLP, or ``None``."""
    if not _otlp_logs_configured():
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http._log_exporter import (
            OTLPLogExporter,
        )

        provider = LoggerProvider(resource=_resource())
        provider.add_log_record_processor(
            BatchLogRecordProcessor(_wrap_exporter("logs", OTLPLogExporter()))
        )
        logger.info(
            "OTLP logs exporter configured, endpoint: %s",
            _effective_endpoint("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT"),
        )
        return provider
    except Exception:  # noqa: BLE001
        logger.warning("OTLP log exporter setup failed", exc_info=True)
        return None


def _resource() -> Any:
    """Build the OTEL resource (``service.name`` / ``service.version``)."""
    from opentelemetry.sdk.resources import Resource

    # OTEL_SERVICE_NAME / OTEL_RESOURCE_ATTRIBUTES in the env override these.
    # service.version comes from the shared resolver (env override → package
    # metadata) so it matches the X-Quartermaster-Version header and the SPA.
    return Resource.create(
        {"service.name": "quartermaster", "service.version": app_version()}
    )


def _effective_endpoint(signal_var: str) -> str:
    """Return the endpoint that the OTEL SDK will use for a given signal.

    The SDK prefers the signal-specific var over the generic base endpoint.
    Falls back to the SDK's compiled-in default when neither is set (which
    only happens when Prometheus-only metrics are active).
    """
    return (
        os.environ.get(signal_var)
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or "http://localhost:4318 (SDK default)"
    )


def _otlp_metrics_configured() -> bool:
    """Return whether an OTLP metrics endpoint is set in the environment."""
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT")
    )


def _otlp_traces_configured() -> bool:
    """Return whether an OTLP traces endpoint is set in the environment."""
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    )


def _otlp_logs_configured() -> bool:
    """Return whether an OTLP logs endpoint is set in the environment."""
    return bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT")
    )


def _create_instruments(meter: Any) -> None:
    """Create every instrument, once per distinct meter object."""
    global _instr_meter
    global _tool_calls, _tool_duration
    global _resolve_calls, _resolve_engine, _resolve_confidence
    global _resolve_coverage, _resolve_broadening
    global _resolve_delivered_tokens, _resolve_offered_tokens
    global _kit_deliveries, _kit_delivered_tokens, _section_deliveries
    global _trait_matched, _gap_requested
    if _instr_meter is meter:
        return
    _instr_meter = meter

    _tool_calls = meter.create_counter(
        "qm.tool.calls", unit="1", description="MCP tool invocations."
    )
    _tool_duration = meter.create_histogram(
        "qm.tool.duration", unit="ms", description="MCP tool call duration."
    )
    _resolve_calls = meter.create_counter(
        "qm.resolve.calls", unit="1", description="resolve_kits invocations."
    )
    _resolve_engine = meter.create_counter(
        "qm.resolve.engine",
        unit="1",
        description="Winning trait-inference engine per resolve.",
    )
    _resolve_confidence = meter.create_counter(
        "qm.resolve.confidence",
        unit="1",
        description="Selection confidence per resolve.",
    )
    _resolve_coverage = meter.create_histogram(
        "qm.resolve.coverage",
        unit="1",
        description="Fraction of trait dimensions covered per resolve.",
    )
    _resolve_broadening = meter.create_counter(
        "qm.resolve.broadening_recommended",
        unit="1",
        description="Resolves where broadening was recommended.",
    )
    _resolve_delivered_tokens = meter.create_histogram(
        "qm.resolve.delivered_tokens",
        unit="token",
        description="Inlined always-load tokens per resolve.",
    )
    _resolve_offered_tokens = meter.create_histogram(
        "qm.resolve.offered_tokens",
        unit="token",
        description="On-demand (offered) tokens per resolve.",
    )
    _kit_deliveries = meter.create_counter(
        "qm.kit.deliveries",
        unit="1",
        description="Kit content deliveries by kit/domain/disposition.",
    )
    _kit_delivered_tokens = meter.create_counter(
        "qm.kit.delivered_tokens",
        unit="token",
        description="Tokens delivered by kit/domain/disposition.",
    )
    _section_deliveries = meter.create_counter(
        "qm.section.deliveries",
        unit="1",
        description="Section deliveries by kit/section/disposition.",
    )
    _trait_matched = meter.create_counter(
        "qm.trait.matched",
        unit="1",
        description="Inferred traits by category/value.",
    )
    _gap_requested = meter.create_counter(
        "qm.gap.requested",
        unit="1",
        description="Kit-gap requests filed by clients.",
    )

    meter.create_observable_gauge(
        "qm.catalog.kits",
        callbacks=[_observe("kits")],
        unit="1",
        description="Kits in the catalog, per domain.",
    )
    meter.create_observable_gauge(
        "qm.catalog.sections",
        callbacks=[_observe("sections")],
        unit="1",
        description="Sections in the catalog, per domain.",
    )
    meter.create_observable_gauge(
        "qm.catalog.total_tokens",
        callbacks=[_observe("total_tokens")],
        unit="token",
        description="Total kit tokens in the catalog, per domain.",
    )
    meter.create_observable_gauge(
        "qm.catalog.always_load_tokens",
        callbacks=[_observe("always_load_tokens")],
        unit="token",
        description="Always-load kit tokens in the catalog, per domain.",
    )


# ---------------------------------------------------------------------------
# Catalog stats (observable-gauge backing)
# ---------------------------------------------------------------------------


@dataclass
class _DomainStats:
    """Per-domain catalog aggregates."""

    kits: int = 0
    sections: int = 0
    total_tokens: int = 0
    always_load_tokens: int = 0


def _observe(field: str) -> Any:
    """Return an observable-gauge callback yielding *field* per domain."""

    def _callback(_options: Any) -> list[Any]:
        try:
            return [
                Observation(getattr(stats, field), {"domain": domain})
                for domain, stats in _catalog_stats().items()
            ]
        except Exception:  # noqa: BLE001 - a scrape must never raise
            logger.debug("catalog gauge %r failed", field, exc_info=True)
            return []

    return _callback


def _catalog_stats() -> dict[str, _DomainStats]:
    """Return per-domain catalog stats, cached by catalog fingerprint."""
    global _stats_cache
    from app.traits import catalog_fingerprint

    try:
        fingerprint = catalog_fingerprint()
    except Exception:  # noqa: BLE001
        fingerprint = ""
    if (
        _stats_cache is not None
        and fingerprint
        and _stats_cache[0] == fingerprint
    ):
        return _stats_cache[1]
    stats = _compute_catalog_stats()
    if fingerprint:
        _stats_cache = (fingerprint, stats)
    return stats


def _compute_catalog_stats() -> dict[str, _DomainStats]:
    """Walk the catalog and tally per-domain kit/section/token counts."""
    from app.kits import iter_catalog, read_kit, read_kit_outline

    stats: dict[str, _DomainStats] = {}
    for info, applicability in iter_catalog():
        domains = applicability.domains or ["unknown"]
        for domain in domains:
            stats.setdefault(domain, _DomainStats()).kits += 1
        outline = read_kit_outline(info.name)
        version = outline["version"]
        for section in outline["sections"]:
            try:
                body = read_kit(info.name, version, [section["id"]])
                toks = count_tokens(body)
            except Exception:  # noqa: BLE001 - estimate if a body won't read
                toks = estimate_tokens_from_bytes(section["bytes"])
            for domain in domains:
                entry = stats[domain]
                entry.sections += 1
                entry.total_tokens += toks
                if section["always_load"]:
                    entry.always_load_tokens += toks
    return stats


def _kit_domains(kit: str) -> list[str]:
    """Return a kit's declared domains, via a refreshing name->domains cache."""
    global _domains_cache
    try:
        if _domains_cache is None or kit not in _domains_cache:
            from app.kits import iter_catalog

            _domains_cache = {
                info.name: (applicability.domains or ["unknown"])
                for info, applicability in iter_catalog()
            }
    except Exception:  # noqa: BLE001
        return ["unknown"]
    return _domains_cache.get(kit) or ["unknown"]


# ---------------------------------------------------------------------------
# Recording helpers (all defensive — never raise into the request path)
# ---------------------------------------------------------------------------


def record_tool_call(tool: str | None, ok: bool, duration_ms: float) -> None:
    """Record one MCP tool invocation (count + duration)."""
    if not _initialized:
        return
    try:
        attrs = {"tool": tool or "unknown", "ok": ok}
        _tool_calls.add(1, attrs)
        _tool_duration.record(duration_ms, attrs)
    except Exception:  # noqa: BLE001
        logger.debug("record_tool_call failed", exc_info=True)


def record_kit_delivery(
    *,
    kit: str,
    disposition: str,
    tokens: int,
    section_ids: list[str],
) -> None:
    """
    Record that *kit* content was delivered to a client.

    :param kit: Kit name.
    :param disposition: ``inlined`` | ``offered`` | ``full`` | ``sections``.
    :param tokens: Token size of the delivered (or offered) content.
    :param section_ids: Section ids involved (only emitted when section-level
        metrics are enabled).
    """
    if not _initialized:
        return
    try:
        for domain in _kit_domains(kit):
            attrs = {
                "kit": kit,
                "domain": domain,
                "disposition": disposition,
            }
            _kit_deliveries.add(1, attrs)
            _kit_delivered_tokens.add(tokens, attrs)
        if _section_level:
            for section_id in section_ids:
                _section_deliveries.add(
                    1,
                    {
                        "kit": kit,
                        "section_id": section_id,
                        "disposition": disposition,
                    },
                )
    except Exception:  # noqa: BLE001
        logger.debug("record_kit_delivery failed", exc_info=True)


def record_resolve(
    *,
    engine: str,
    confidence: str,
    coverage: float,
    broadening_recommended: bool,
    delivered_tokens: int,
    offered_tokens: int,
    traits: dict[str, list[str]],
) -> None:
    """Record per-call ``resolve_kits`` metrics (no task text)."""
    if not _initialized:
        return
    try:
        _resolve_calls.add(1)
        _resolve_engine.add(1, {"engine": engine})
        _resolve_confidence.add(1, {"confidence": confidence})
        _resolve_coverage.record(float(coverage))
        if broadening_recommended:
            _resolve_broadening.add(1)
        _resolve_delivered_tokens.record(delivered_tokens)
        _resolve_offered_tokens.record(offered_tokens)
        for category, values in traits.items():
            for value in values:
                _trait_matched.add(1, {"category": category, "value": value})
    except Exception:  # noqa: BLE001
        logger.debug("record_resolve failed", exc_info=True)


def record_gap_request() -> None:
    """Record that a client filed a kit-gap request."""
    if not _initialized:
        return
    try:
        _gap_requested.add(1)
    except Exception:  # noqa: BLE001
        logger.debug("record_gap_request failed", exc_info=True)


# ---------------------------------------------------------------------------
# Tracing helpers
# ---------------------------------------------------------------------------


class _NullSpan:
    """A no-op span used when tracing is unavailable."""

    def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
        """Ignore attribute writes."""
        return None


def set_attrs(span: Any, attributes: dict[str, Any] | None) -> None:
    """Set span attributes defensively (skips ``None`` values)."""
    if span is None or not attributes:
        return
    try:
        for key, value in attributes.items():
            if value is None:
                continue
            span.set_attribute(key, value)
    except Exception:  # noqa: BLE001
        logger.debug("set_attrs failed", exc_info=True)


@contextlib.contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    """
    Start a span as the current span, yielding it (or a no-op span).

    Always safe: when tracing is unconfigured or OpenTelemetry is absent it
    yields a :class:`_NullSpan` whose ``set_attribute`` is a no-op.

    :param name: Span name.
    :param attributes: Optional initial attributes.
    :yields: The active span (or a no-op span).
    """
    tracer = _tracer
    if tracer is None or not _OTEL_AVAILABLE:
        yield _NullSpan()
        return
    try:
        manager = tracer.start_as_current_span(name)
    except Exception:  # noqa: BLE001
        yield _NullSpan()
        return
    with manager as active:
        set_attrs(active, attributes)
        yield active


# ---------------------------------------------------------------------------
# Prometheus pull endpoint support
# ---------------------------------------------------------------------------


def prometheus_enabled() -> bool:
    """Return whether a Prometheus reader was installed (so ``/metrics``
    can serve)."""
    return _prometheus_enabled


def prometheus_exposition() -> tuple[bytes, str]:
    """Return the Prometheus exposition payload and its content type."""
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

    return generate_latest(), CONTENT_TYPE_LATEST


def reset_for_test() -> None:
    """Clear cached catalog/domain state and force instrument rebuild.

    Test-only helper so a fresh injected provider rebuilds instruments and
    stale per-fixture catalog caches do not leak across tests.
    """
    global _stats_cache, _domains_cache, _instr_meter
    _stats_cache = None
    _domains_cache = None
    _instr_meter = None
    _export_state.clear()
