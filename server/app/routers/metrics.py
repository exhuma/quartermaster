"""
In-app metrics API for the Metrics dashboard.

Read-only endpoint that aggregates the always-on local event store
(:mod:`app.observability.local_store`) into a single bundle the SPA renders as
ECharts graphs. It answers: which kits are used a lot / almost none, how many
tokens are sent back to clients, and how distinct kits are (structural trait
overlap + behavioural co-occurrence), plus selection health, tool latency, and
catalog growth.

This path is deliberately independent of OpenTelemetry: it reads the local
SQLite store, not the OTLP exporters, so the dashboard works even when OTEL is
broken or unconfigured. The bundle's ``meta.otel_status`` reports the OTLP
export state so the UI can badge it without depending on it.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app import telemetry
from app.kits import list_all_kits
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.observability import local_store

router = APIRouter(
    prefix="/api",
    tags=["metrics"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
    responses={406: {"description": "Vendor media type not requested."}},
)


def _otel_status() -> str:
    """Summarise OTLP export health for the UI badge.

    ``inert`` = no OTLP exporter configured (nothing to export); ``exporting``
    = all configured signals exported OK; ``failing`` = at least one export
    failed; ``configured`` = exporters set up but nothing exported yet.
    """
    try:
        health = telemetry.export_health()
    except Exception:  # noqa: BLE001 - the dashboard never depends on OTEL
        return "unknown"
    if not health:
        return "inert"
    if any(entry.get("ok") is False for entry in health):
        return "failing"
    if all(entry.get("ok") is True for entry in health):
        return "exporting"
    return "configured"


def build_overview(
    window: str, granularity: str = local_store.DEFAULT_GRANULARITY
) -> dict[str, Any]:
    """Assemble the dashboard bundle for the requested time *window*.

    The effective window is capped to the store's retention. *granularity*
    (``1h``/``1d``) sets the bucket size of the time-series (tokens + catalog
    growth). When the local store is disabled/unavailable the event-derived
    series are empty, but the static structural-overlap matrix is still
    computed from the catalog.
    """
    window_seconds = local_store._WINDOWS.get(
        window, local_store._WINDOWS[local_store.DEFAULT_WINDOW]
    )
    retention = local_store.retention_days()
    if retention:
        window_seconds = min(window_seconds, retention * 86_400)
    now = time.time()
    cutoff = now - window_seconds

    store = local_store.get_store()
    if store is not None:
        kit_usage = store.kit_usage(cutoff)
        tokens_timeseries = store.tokens_timeseries(cutoff, granularity)
        resolve_health = store.resolve_health(cutoff)
        tool_latency = store.tool_latency(cutoff)
        co_occurrence = store.co_occurrence(cutoff)
        catalog_growth = store.catalog_growth(cutoff, granularity)
    else:
        kit_usage = []
        tokens_timeseries = []
        resolve_health = {
            "total_calls": 0,
            "engine_mix": {},
            "confidence_mix": {},
            "coverage_p50": 0.0,
            "coverage_p95": 0.0,
            "broadening_rate": 0.0,
        }
        tool_latency = []
        co_occurrence = {"kits": [], "cells": []}
        catalog_growth = {"catalog": [], "delivered": []}

    return {
        "meta": {
            "window": window,
            "granularity": granularity,
            "generated_at": now,
            "retention_days": retention,
            "store_enabled": store is not None,
            "otel_status": _otel_status(),
        },
        "kit_usage": kit_usage,
        "tokens_timeseries": tokens_timeseries,
        "resolve_health": resolve_health,
        "tool_latency": tool_latency,
        "co_occurrence": co_occurrence,
        "structural_overlap": local_store.structural_overlap(),
        "catalog_growth": catalog_growth,
    }


@router.get("/metrics/overview")
def metrics_overview(
    window: str = Query(
        default=local_store.DEFAULT_WINDOW,
        description="Time window: 24h, 7d, or 30d (capped to retention).",
    ),
    granularity: str = Query(
        default=local_store.DEFAULT_GRANULARITY,
        description="Time-series bucket size: 1h or 1d.",
    ),
) -> dict[str, Any]:
    """Return the aggregated metrics bundle for the Metrics dashboard."""
    if window not in local_store._WINDOWS:
        window = local_store.DEFAULT_WINDOW
    if granularity not in local_store._GRANULARITY_FORMATS:
        granularity = local_store.DEFAULT_GRANULARITY
    return build_overview(window, granularity)


@router.get("/kits/{name}/version-adoption")
def kit_version_adoption(
    name: str,
    window: str = Query(
        default=local_store.DEFAULT_WINDOW,
        description="Time window: 24h, 7d, or 30d (capped to retention).",
    ),
    granularity: str = Query(
        default=local_store.DEFAULT_GRANULARITY,
        description="Time-series bucket size: 1h or 1d.",
    ),
) -> dict[str, Any]:
    """Return per-bucket version-adoption for one kit.

    Powers the per-kit chart on the kit detail page. Reads the isolated
    ``kit_version_uses`` telemetry, so it only reflects usage recorded
    since version pinning shipped (empty until data accrues).
    """
    known = {k.name: k for k in list_all_kits()}
    if name not in known:
        raise HTTPException(
            status_code=404, detail=f"Kit not found: {name!r}"
        )
    available = known[name].versions

    if window not in local_store._WINDOWS:
        window = local_store.DEFAULT_WINDOW
    if granularity not in local_store._GRANULARITY_FORMATS:
        granularity = local_store.DEFAULT_GRANULARITY

    window_seconds = local_store._WINDOWS[window]
    retention = local_store.retention_days()
    if retention:
        window_seconds = min(window_seconds, retention * 86_400)
    now = time.time()
    cutoff = now - window_seconds

    store = local_store.get_store()
    if store is not None:
        adoption = store.version_adoption(name, cutoff, granularity)
    else:
        adoption = {
            "granularity": granularity,
            "versions": [],
            "buckets": [],
        }

    return {
        "meta": {
            "kit": name,
            "window": window,
            "granularity": granularity,
            "generated_at": now,
            "retention_days": retention,
            "store_enabled": store is not None,
            "available_versions": available,
        },
        **adoption,
    }
