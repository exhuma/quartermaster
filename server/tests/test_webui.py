"""
Tests for serving the built SPA and its runtime config.js.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import webui


def _fake_settings() -> SimpleNamespace:
    return SimpleNamespace(
        server_origin="https://instructions.example.com",
        keycloak_issuer="https://auth.example.com/realms/master",
        webui_keycloak_client_id="quartermaster-webui",
        oauth_scopes=["openid", "profile", "email"],
    )


def test_render_config_js_shape() -> None:
    js = webui.render_config_js(_fake_settings())
    assert js.startswith("window.__APP_CONFIG__ = ")
    cfg = webui.runtime_config(_fake_settings())
    assert cfg["oidcAuthority"] == "https://auth.example.com/realms/master"
    assert cfg["oidcClientId"] == "quartermaster-webui"
    assert cfg["oidcRedirectUri"].endswith("/auth/callback")
    assert cfg["apiBaseUrl"] == ""


def test_no_build_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEBUI_DIST", "/nonexistent/dist")
    app = FastAPI()
    webui.mount_webui(app)
    # No SPA routes were added.
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/config.js" not in paths


@pytest.fixture()
def spa_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "app.js").write_text("console.log('hi')")
    monkeypatch.setenv("WEBUI_DIST", str(dist))
    monkeypatch.setattr(webui, "get_settings", _fake_settings)
    app = FastAPI()

    @app.get("/api/kits")
    def kits() -> dict:
        return {"ok": True}

    webui.mount_webui(app)
    return TestClient(app)


def test_serves_index_at_root(spa_app: TestClient) -> None:
    resp = spa_app.get("/")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text


def test_spa_fallback_serves_index(spa_app: TestClient) -> None:
    # A client-side route refresh returns the shell.
    resp = spa_app.get("/integration")
    assert resp.status_code == 200
    assert "<title>app</title>" in resp.text


def test_config_js_served(spa_app: TestClient) -> None:
    resp = spa_app.get("/config.js")
    assert resp.status_code == 200
    assert "application/javascript" in resp.headers["content-type"]
    assert "window.__APP_CONFIG__" in resp.text


def test_assets_served(spa_app: TestClient) -> None:
    resp = spa_app.get("/assets/app.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_unknown_api_path_is_404_not_shell(spa_app: TestClient) -> None:
    # The fallback must not swallow unknown API paths.
    resp = spa_app.get("/api/does-not-exist")
    assert resp.status_code == 404
    assert "<title>" not in resp.text


def test_real_api_route_still_works(spa_app: TestClient) -> None:
    assert spa_app.get("/api/kits").json() == {"ok": True}
