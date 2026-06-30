"""Health probes (module-observability-healthz).

Three endpoints with distinct semantics:

- ``GET /livez`` — process liveness only; never calls external dependencies.
- ``GET /readyz`` — readiness to serve core traffic; checks only the required
  dependency (the kit catalog at ``kits_root``).
- ``GET /healthz`` — summarized operational health; adds the optional Keycloak
  JWKS reachability check and, when OTLP export is configured, a passive
  per-signal telemetry-export check (reflecting the SDK's last real export, so
  the probe sends nothing). Both degrade (rather than fail) when unhealthy.

Payloads are security-minimized: no secrets, hostnames, ports, versions, or
exception text — only abstract, stable ``reason_code`` values. Status maps to
HTTP ``200`` (ok/degraded) or ``503`` (fail).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import httpx
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import telemetry
from app.auth import _build_ssl_context
from app.config import Settings, get_settings

OK = "ok"
DEGRADED = "degraded"
FAIL = "fail"
UNKNOWN = "unknown"

_KEYCLOAK_TIMEOUT_SECONDS = 2.0


class ComponentHealth(BaseModel):
    """Health of a single dependency (security-minimized)."""

    name: str
    kind: str
    required: bool
    status: str
    reason_code: str
    latency_ms: int | None = None


class HealthResponse(BaseModel):
    """Compact probe response schema."""

    probe: str
    status: str
    checked_at: str
    components: list[ComponentHealth]


def _now() -> str:
    """Return the current time as an RFC 3339 timestamp."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _check_kits_root(settings: Settings) -> ComponentHealth:
    """Check all configured kit catalog layers are present and readable."""
    start = time.monotonic()
    layers = settings.effective_layers
    ok = all(layer.path.is_dir() for layer in layers)
    latency = round((time.monotonic() - start) * 1000)
    return ComponentHealth(
        name="kit-catalog",
        kind="storage",
        required=True,
        status=OK if ok else FAIL,
        reason_code="ok" if ok else "unavailable",
        latency_ms=latency,
    )


def _check_keycloak(settings: Settings) -> ComponentHealth:
    """Probe Keycloak JWKS reachability (optional, bounded timeout)."""
    start = time.monotonic()
    status = UNKNOWN
    reason = "timeout"
    verify = _build_ssl_context(settings) or True
    try:
        resp = httpx.get(
            settings.jwks_url,
            timeout=_KEYCLOAK_TIMEOUT_SECONDS,
            verify=verify,
        )
        if resp.status_code == 200:
            status, reason = OK, "ok"
        else:
            status, reason = FAIL, "unexpected_status"
    except httpx.TimeoutException:
        status, reason = UNKNOWN, "timeout"
    except httpx.HTTPError:
        status, reason = FAIL, "unreachable"
    latency = round((time.monotonic() - start) * 1000)
    return ComponentHealth(
        name="identity-provider",
        kind="api",
        required=False,
        status=status,
        reason_code=reason,
        latency_ms=latency,
    )


def _check_otlp() -> list[ComponentHealth]:
    """Report OTLP export health per configured signal (passive).

    Reads the outcome of the SDK's most recent real export — the probe sends
    nothing itself. Returns one optional component per OTLP signal that has an
    exporter installed (empty when OTLP is not configured). An export that has
    not happened yet is reported ``ok`` (``no_data_yet``) rather than failing,
    since the batch processors for traces/logs only export when there is
    activity; only an actual export *failure* degrades health.
    """
    components: list[ComponentHealth] = []
    for entry in telemetry.export_health():
        ok = entry["ok"]
        if ok is False:
            status, reason = FAIL, "export_failed"
        elif ok is True:
            status, reason = OK, "ok"
        else:
            status, reason = OK, "no_data_yet"
        components.append(
            ComponentHealth(
                name=f"telemetry-{entry['signal']}",
                kind="exporter",
                required=False,
                status=status,
                reason_code=reason,
            )
        )
    return components


def _http_status(status: str) -> int:
    """Map an endpoint status to its HTTP status code."""
    return 503 if status == FAIL else 200


def _response(body: HealthResponse) -> JSONResponse:
    """Serialize *body* with the kit's HTTP status mapping."""
    return JSONResponse(
        status_code=_http_status(body.status),
        content=body.model_dump(),
        headers={"Cache-Control": "no-store"},
    )


async def livez() -> JSONResponse:
    """Process liveness — always ``ok`` while the worker can respond."""
    body = HealthResponse(
        probe="livez", status=OK, checked_at=_now(), components=[]
    )
    return _response(body)


async def readyz() -> JSONResponse:
    """Readiness — required dependencies only (the kit catalog)."""
    settings = get_settings()
    components = [_check_kits_root(settings)]
    required_bad = any(
        c.required and c.status in (FAIL, UNKNOWN) for c in components
    )
    status = FAIL if required_bad else OK
    body = HealthResponse(
        probe="readyz",
        status=status,
        checked_at=_now(),
        components=components,
    )
    return _response(body)


async def healthz() -> JSONResponse:
    """Summarized health — required plus optional (Keycloak) dependencies."""
    settings = get_settings()
    components = [
        _check_kits_root(settings),
        _check_keycloak(settings),
        *_check_otlp(),
    ]
    required_bad = any(
        c.required and c.status in (FAIL, UNKNOWN) for c in components
    )
    optional_bad = any(
        not c.required and c.status in (FAIL, UNKNOWN) for c in components
    )
    if required_bad:
        status = FAIL
    elif optional_bad:
        status = DEGRADED
    else:
        status = OK
    body = HealthResponse(
        probe="healthz",
        status=status,
        checked_at=_now(),
        components=components,
    )
    return _response(body)
