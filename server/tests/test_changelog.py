"""Tests for the public changelog endpoint and its loader.

The changelog is served verbatim from the clproc-rendered bundled asset
(``app/assets/text/changelog.json``) over a public, unauthenticated path so the
web UI can show it before sign-in.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app import changelog as changelog_mod
from app.config import get_settings


def _make_client(monkeypatch, tmp_path: Path) -> TestClient:
    kits = tmp_path / "kits"
    kits.mkdir()
    env = {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(kits),
        "WEBUI_DIST": "/nonexistent",
    }
    for key, value in env.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


def test_changelog_public_no_auth(monkeypatch, tmp_path) -> None:
    """The changelog is reachable with no Authorization and no vendor Accept."""
    client = _make_client(monkeypatch, tmp_path)
    # No Authorization header, and the default Accept is */* (not the vendor
    # media type the /api routers demand) — the changelog must still serve.
    resp = client.get("/changelog.json")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    get_settings.cache_clear()


def test_changelog_shape(monkeypatch, tmp_path) -> None:
    """The served payload is the clproc release array with the expected keys."""
    client = _make_client(monkeypatch, tmp_path)
    body = client.get("/changelog.json").json()
    assert isinstance(body, list) and body, "expected a non-empty release array"
    for release in body:
        assert "logs" in release and "meta" in release
        assert {"version", "date", "notes"} <= release["meta"].keys()
        for log in release["logs"]:
            assert {"subject", "type", "is_highlight"} <= log.keys()
    # The newest (unreleased) group carries a null date; at least one entry is
    # flagged as a highlight (the important MCP-behaviour milestones).
    assert body[0]["meta"]["date"] is None
    assert any(
        log["is_highlight"] for release in body for log in release["logs"]
    )
    get_settings.cache_clear()


def test_changelog_audience_prefixes_present(monkeypatch, tmp_path) -> None:
    """Subjects carry the [MCP]/[UI]/... audience marker the UI turns into a chip."""
    client = _make_client(monkeypatch, tmp_path)
    subjects = [
        log["subject"]
        for release in client.get("/changelog.json").json()
        for log in release["logs"]
    ]
    assert any(s.startswith("[MCP]") for s in subjects)
    assert any(s.startswith("[UI]") for s in subjects)
    get_settings.cache_clear()


def test_load_changelog_json_degrades_when_asset_missing(monkeypatch) -> None:
    """A missing generated asset serves an empty array rather than erroring."""

    def _raise(*_parts: str) -> str:
        raise FileNotFoundError

    monkeypatch.setattr(changelog_mod, "load_asset", _raise)
    assert json.loads(changelog_mod.load_changelog_json()) == []
