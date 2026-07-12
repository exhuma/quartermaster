"""
Tests for serving the rendered Sphinx documentation site at ``/docs``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app import docs_site


def test_no_build_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QM_DOCS_DIST", "/nonexistent/docs")
    app = FastAPI()
    docs_site.mount_docs(app)
    # Nothing named "docs" was mounted.
    assert not any(getattr(r, "name", "") == "docs" for r in app.routes)


@pytest.fixture()
def docs_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    dist = tmp_path / "docs_dist"
    (dist / "user").mkdir(parents=True)
    (dist / "index.html").write_text(
        "<!doctype html><title>Quartermaster documentation</title>"
    )
    (dist / "user" / "index.html").write_text(
        "<!doctype html><title>Users</title>"
    )
    monkeypatch.setenv("QM_DOCS_DIST", str(dist))
    app = FastAPI()

    # A SPA-style catch-all added AFTER mount_docs must not shadow /docs.
    docs_site.mount_docs(app)

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str) -> PlainTextResponse:
        if full_path.startswith(("api/", "kits/")):
            raise HTTPException(status_code=404)
        return PlainTextResponse("<title>app shell</title>")

    return TestClient(app)


def test_serves_docs_index(docs_app: TestClient) -> None:
    # html=True serves index.html for the directory path.
    resp = docs_app.get("/docs/")
    assert resp.status_code == 200
    assert "Quartermaster documentation" in resp.text


def test_serves_nested_docs_page(docs_app: TestClient) -> None:
    resp = docs_app.get("/docs/user/")
    assert resp.status_code == 200
    assert "<title>Users</title>" in resp.text


def test_docs_mount_beats_spa_fallback(docs_app: TestClient) -> None:
    # The /docs mount is matched ahead of the catch-all, so the docs index —
    # not the SPA shell — is served.
    resp = docs_app.get("/docs/index.html")
    assert resp.status_code == 200
    assert "app shell" not in resp.text
    assert "Quartermaster documentation" in resp.text
