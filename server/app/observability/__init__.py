"""
In-app observability that does not depend on OpenTelemetry.

:mod:`app.telemetry` exports metrics/traces to OTEL collectors, but only when
an OTLP endpoint or Prometheus scrape is configured, and its recording helpers
go inert when OTEL is not initialised. This package provides a small,
always-on **local** event store (SQLite, rolling window, survives restarts)
plus catalog-derived "distinctness" analysis, feeding the in-app Metrics
dashboard so usage is visible even when OTEL is broken or unconfigured.

Long-term/production metrics still delegate to OTEL → Grafana (see
``docs/operator/observability.md``); this store is a short, capped complement.
"""
