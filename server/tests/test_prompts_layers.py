"""
Tests for multi-layer prompt support: layer-scoped CRUD, readonly
enforcement, and route-registration precedence over the merged-view router.

Mirrors ``tests/test_kits_layers.py`` but for the sectionless prompts
catalog.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import KitLayerConfig
from app.main import _register_exception_handlers
from app.media_types import VENDOR_MEDIA_TYPE
from app.routers import prompts_admin, prompts_layers


@pytest.fixture()
def two_layers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()
    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    settings = SimpleNamespace(
        effective_prompt_layers=layers,
        private_prompts_root=tmp_path / "private-prompts",
    )
    monkeypatch.setattr("app.prompt_catalog.get_settings", lambda: settings)
    return SimpleNamespace(base=base, overlay=overlay)


@pytest.fixture()
def client(two_layers, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("app.authz.is_editor", lambda _sub: True)
    app = FastAPI()
    # Registration order matters: prompts_layers before prompts_admin, so
    # /api/prompts/layers is not swallowed by /api/prompts/{name}.
    app.include_router(prompts_layers.router)
    app.include_router(prompts_admin.router)
    _register_exception_handlers(app)
    return TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


def _write(root: Path, name: str, body: str) -> None:
    (root / f"{name}.md").write_text(body, encoding="utf-8")


def test_list_layers(client: TestClient) -> None:
    layers = client.get("/api/prompts/layers").json()
    assert [entry["name"] for entry in layers] == ["base", "overlay"]
    assert layers[0]["readonly"] is True
    assert layers[1]["readonly"] is False


def test_layers_route_not_swallowed_by_name_route(
    client: TestClient, two_layers
) -> None:
    """/api/prompts/layers must list layers, not 404 as prompt name 'layers'."""
    resp = client.get("/api/prompts/layers")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    assert all("readonly" in entry for entry in resp.json())


def test_create_in_overlay_layer(client: TestClient, two_layers) -> None:
    resp = client.post(
        "/api/prompts/layers/overlay",
        json={
            "name": "over-prompt",
            "title": "",
            "description": "",
            "body": "x",
        },
    )
    assert resp.status_code == 201, resp.text
    assert resp.headers["Location"] == "/api/prompts/layers/overlay/over-prompt"
    assert (two_layers.overlay / "over-prompt.md").exists()


def test_create_in_readonly_base_layer_is_403(
    client: TestClient, two_layers
) -> None:
    resp = client.post(
        "/api/prompts/layers/base",
        json={"name": "x", "title": "", "description": "", "body": "y"},
    )
    assert resp.status_code == 403


def test_overlay_shadows_base_in_merged_view(
    client: TestClient, two_layers
) -> None:
    _write(two_layers.base, "shared", "Base version.")
    _write(two_layers.overlay, "shared", "Overlay version.")
    merged = client.get("/api/prompts/shared").json()
    assert merged["body"] == "Overlay version."
    assert merged["source_layer"] == "overlay"


def test_base_only_prompt_still_appears_in_merged_view(
    client: TestClient, two_layers
) -> None:
    _write(two_layers.base, "base-only", "Base body.")
    merged = client.get("/api/prompts/base-only").json()
    assert merged["body"] == "Base body."
    assert merged["source_layer"] == "base"
    assert merged["editable"] is False


def test_list_prompts_in_layer_is_unmerged(
    client: TestClient, two_layers
) -> None:
    _write(two_layers.base, "base-only", "Base body.")
    _write(two_layers.overlay, "overlay-only", "Overlay body.")
    base_listing = client.get("/api/prompts/layers/base").json()
    assert [p["name"] for p in base_listing] == ["base-only"]
    overlay_listing = client.get("/api/prompts/layers/overlay").json()
    assert [p["name"] for p in overlay_listing] == ["overlay-only"]


def test_put_and_delete_in_overlay_layer(
    client: TestClient, two_layers
) -> None:
    client.post(
        "/api/prompts/layers/overlay",
        json={"name": "editable", "title": "", "description": "", "body": "v1"},
    )
    resp = client.put(
        "/api/prompts/layers/overlay/editable",
        json={"title": "", "description": "", "body": "v2"},
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "v2"

    deleted = client.delete("/api/prompts/layers/overlay/editable")
    assert deleted.status_code == 204
    assert not (two_layers.overlay / "editable.md").exists()


def test_delete_in_readonly_base_layer_is_403(
    client: TestClient, two_layers
) -> None:
    _write(two_layers.base, "base-only", "Base body.")
    resp = client.delete("/api/prompts/layers/base/base-only")
    assert resp.status_code == 403


def test_unknown_layer_is_404(client: TestClient) -> None:
    assert client.get("/api/prompts/layers/nope").status_code == 404
