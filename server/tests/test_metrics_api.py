"""
Tests for the in-app metrics API (``GET /api/metrics/overview``).

The router is mounted on a bare FastAPI app (no JWT/UA middleware) to isolate
the endpoint contract: vendor ``Accept`` negotiation and the overview bundle
shape. The aggregation itself is covered by ``test_metrics_local_store``; here
we assert the bundle is well-formed both with an initialised store and when the
store is disabled (empty series, but structural overlap still present).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.media_types import VENDOR_MEDIA_TYPE
from app.observability import local_store
from app.routers import metrics as metrics_router


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    local_store.reset_for_tests()
    store = local_store.LocalMetricsStore(
        tmp_path / "metrics.db", retention_days=7
    )
    store.init()
    local_store._store = store  # install as the process-wide store
    app = FastAPI()
    app.include_router(metrics_router.router)
    yield TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})
    local_store.reset_for_tests()


_BUNDLE_KEYS = {
    "meta",
    "kit_usage",
    "tokens_timeseries",
    "resolve_health",
    "tool_latency",
    "co_occurrence",
    "structural_overlap",
    "catalog_growth",
}


def test_overview_returns_vendor_bundle(client: TestClient) -> None:
    resp = client.get("/api/metrics/overview")
    assert resp.status_code == 200
    assert VENDOR_MEDIA_TYPE in resp.headers["content-type"]
    body = resp.json()
    assert _BUNDLE_KEYS.issubset(body.keys())
    assert body["meta"]["store_enabled"] is True
    assert body["meta"]["otel_status"] == "inert"  # no OTLP configured in tests


def test_overview_rejects_bare_json(client: TestClient) -> None:
    resp = client.get(
        "/api/metrics/overview", headers={"Accept": "application/json"}
    )
    assert resp.status_code == 406


def test_overview_reflects_recorded_usage(client: TestClient) -> None:
    store = local_store.get_store()
    store.record_delivery(kit="kit-a", disposition="full", tokens=123)
    resp = client.get("/api/metrics/overview?window=24h")
    body = resp.json()
    assert body["meta"]["window"] == "24h"
    usage = {r["kit"]: r for r in body["kit_usage"]}
    assert usage["kit-a"]["tokens"] == 123


def test_unknown_window_falls_back_to_default(client: TestClient) -> None:
    resp = client.get("/api/metrics/overview?window=bogus")
    assert resp.status_code == 200
    assert resp.json()["meta"]["window"] == local_store.DEFAULT_WINDOW


def test_granularity_reflected_in_meta(client: TestClient) -> None:
    resp = client.get("/api/metrics/overview?window=24h&granularity=1h")
    assert resp.status_code == 200
    assert resp.json()["meta"]["granularity"] == "1h"


def test_unknown_granularity_falls_back_to_default(client: TestClient) -> None:
    resp = client.get("/api/metrics/overview?granularity=bogus")
    assert resp.status_code == 200
    assert resp.json()["meta"]["granularity"] == local_store.DEFAULT_GRANULARITY


def test_overview_without_store_still_serves(tmp_path: Path) -> None:
    # No store installed → event series empty, structural overlap still runs.
    local_store.reset_for_tests()
    app = FastAPI()
    app.include_router(metrics_router.router)
    http = TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})
    body = http.get("/api/metrics/overview").json()
    assert body["meta"]["store_enabled"] is False
    assert body["kit_usage"] == []
    assert "structural_overlap" in body


# ---------------------------------------------------------------------------
# Per-kit version-adoption route
# ---------------------------------------------------------------------------


def _fake_kits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.kits import KitInfo

    monkeypatch.setattr(
        metrics_router,
        "list_all_kits",
        lambda: [
            KitInfo(
                name="kit-alpha",
                description="d",
                versions=["v1", "v2"],
                latest_version="v2",
            )
        ],
    )


def test_version_adoption_returns_vendor_series(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_kits(monkeypatch)
    store = local_store.get_store()
    store.record_kit_version_use(kit="kit-alpha", version="v1")
    store.record_kit_version_use(kit="kit-alpha", version="v2")
    store.record_kit_version_use(kit="kit-alpha", version="v2")

    resp = client.get("/api/kits/kit-alpha/version-adoption")
    assert resp.status_code == 200
    assert VENDOR_MEDIA_TYPE in resp.headers["content-type"]
    body = resp.json()
    assert body["meta"]["kit"] == "kit-alpha"
    assert body["meta"]["available_versions"] == ["v1", "v2"]
    assert body["versions"] == ["v1", "v2"]
    assert len(body["buckets"]) == 1
    assert body["buckets"][0]["counts"] == {"v1": 1, "v2": 2}


def test_version_adoption_unknown_kit_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_kits(monkeypatch)
    resp = client.get("/api/kits/ghost/version-adoption")
    assert resp.status_code == 404


def test_version_adoption_rejects_bare_json(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_kits(monkeypatch)
    resp = client.get(
        "/api/kits/kit-alpha/version-adoption",
        headers={"Accept": "application/json"},
    )
    assert resp.status_code == 406
