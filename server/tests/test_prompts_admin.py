"""Integration tests for the merged-view ``/api/prompts`` admin router."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import KitLayerConfig
from app.main import _register_exception_handlers
from app.media_types import VENDOR_MEDIA_TYPE
from app.routers import prompts_admin


@pytest.fixture()
def prompts_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "prompts"
    root.mkdir()
    layers = [KitLayerConfig(name="default", path=root, readonly=False)]
    settings = SimpleNamespace(
        effective_prompt_layers=layers,
        private_prompts_root=tmp_path / "private-prompts",
    )
    monkeypatch.setattr("app.prompt_catalog.get_settings", lambda: settings)
    return root


@pytest.fixture()
def client(prompts_root: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # These tests cover CRUD behavior, not authorization (that's the
    # writes-require-editor test below); act as an editor everywhere else.
    monkeypatch.setattr("app.authz.is_editor", lambda _sub: True)
    app = FastAPI()
    app.include_router(prompts_admin.router)
    _register_exception_handlers(app)
    return TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


def _payload(name: str = "my-prompt", **overrides) -> dict:
    base = {
        "name": name,
        "title": "My Prompt",
        "description": "A prompt.",
        "body": "Do the thing.",
    }
    base.update(overrides)
    return base


def test_create_list_get_delete(client: TestClient) -> None:
    created = client.post("/api/prompts", json=_payload())
    assert created.status_code == 201, created.text
    assert created.headers["Location"] == "/api/prompts/my-prompt"

    listing = client.get("/api/prompts").json()
    assert [p["name"] for p in listing] == ["my-prompt"]
    assert listing[0]["title"] == "My Prompt"

    detail = client.get("/api/prompts/my-prompt").json()
    assert detail["title"] == "My Prompt"
    assert detail["description"] == "A prompt."
    assert detail["body"] == "Do the thing."
    assert detail["editable"] is True
    assert detail["source_layer"] == "default"

    assert client.delete("/api/prompts/my-prompt").status_code == 204
    assert client.get("/api/prompts/my-prompt").status_code == 404


def test_put_replaces_existing_prompt(client: TestClient) -> None:
    client.post("/api/prompts", json=_payload())
    resp = client.put(
        "/api/prompts/my-prompt",
        json={"title": "Updated", "description": "", "body": "New body."},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["body"] == "New body."
    assert resp.json()["title"] == "Updated"
    assert resp.json()["description"] == ""


def test_put_creates_when_absent(client: TestClient) -> None:
    resp = client.put(
        "/api/prompts/brand-new",
        json={"title": "", "description": "", "body": "Body."},
    )
    assert resp.status_code == 200, resp.text
    assert client.get("/api/prompts/brand-new").status_code == 200


def test_create_rejects_name_reserved_by_canned_prompt(
    client: TestClient,
) -> None:
    resp = client.post("/api/prompts", json=_payload(name="greet"))
    assert resp.status_code == 409


def test_create_rejects_invalid_name(client: TestClient) -> None:
    resp = client.post("/api/prompts", json=_payload(name="Not Valid!"))
    assert resp.status_code == 400


def test_create_invalid_content_is_422(client: TestClient) -> None:
    # An embedded newline in the title breaks the frontmatter round-trip.
    resp = client.post("/api/prompts", json=_payload(title="Bad\nTitle"))
    assert resp.status_code == 422


def test_get_unknown_prompt_is_404(client: TestClient) -> None:
    assert client.get("/api/prompts/nope").status_code == 404


def test_delete_is_idempotent(client: TestClient) -> None:
    assert client.delete("/api/prompts/nope").status_code == 204


def test_writes_require_editor(prompts_root: Path) -> None:
    # No is_editor monkeypatch here, and no auth_sub set: the default
    # (fail-closed) role lookup applies, so writes must be rejected.
    app = FastAPI()
    app.include_router(prompts_admin.router)
    _register_exception_handlers(app)
    client = TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})

    assert client.post("/api/prompts", json=_payload()).status_code == 403
    assert (
        client.put(
            "/api/prompts/x",
            json={"title": "", "description": "", "body": "b"},
        ).status_code
        == 403
    )
    assert client.delete("/api/prompts/x").status_code == 403
    # Reads remain open.
    assert client.get("/api/prompts").status_code == 200
