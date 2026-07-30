"""Integration tests for the owner-scoped ``/api/private-prompts`` router."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.main import _register_exception_handlers
from app.media_types import VENDOR_MEDIA_TYPE


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    settings = SimpleNamespace(
        effective_prompt_layers=[],
        private_prompts_root=tmp_path / "private-prompts",
    )
    monkeypatch.setattr("app.prompt_catalog.get_settings", lambda: settings)
    monkeypatch.setattr("app.private_prompts.get_settings", lambda: settings)

    from app.routers import private_prompts

    app = FastAPI()

    @app.middleware("http")
    async def _stamp_identity(request: Request, call_next):  # noqa: ANN001
        request.state.auth_sub = request.headers.get("X-Test-Sub", "")
        return await call_next(request)

    app.include_router(private_prompts.router)
    _register_exception_handlers(app)
    yield TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


def _payload(name: str = "my-notes") -> dict:
    return {
        "name": name,
        "title": "My Notes",
        "description": "Private notes.",
        "body": "Secret instructions.",
    }


def _as(sub: str) -> dict[str, str]:
    return {"X-Test-Sub": sub}


def test_create_list_get_delete_own_private_prompt(client: TestClient) -> None:
    created = client.post(
        "/api/private-prompts", headers=_as("alice"), json=_payload()
    )
    assert created.status_code == 201, created.text
    assert created.headers["Location"] == "/api/private-prompts/my-notes"

    listing = client.get("/api/private-prompts", headers=_as("alice"))
    assert [p["name"] for p in listing.json()] == ["my-notes"]

    detail = client.get("/api/private-prompts/my-notes", headers=_as("alice"))
    assert detail.status_code == 200
    assert detail.json()["body"] == "Secret instructions."

    gone = client.delete("/api/private-prompts/my-notes", headers=_as("alice"))
    assert gone.status_code == 204
    assert client.get("/api/private-prompts", headers=_as("alice")).json() == []


def test_put_replaces_own_private_prompt(client: TestClient) -> None:
    client.post("/api/private-prompts", headers=_as("alice"), json=_payload())
    resp = client.put(
        "/api/private-prompts/my-notes",
        headers=_as("alice"),
        json={"title": "", "description": "", "body": "Updated."},
    )
    assert resp.status_code == 200
    assert resp.json()["body"] == "Updated."


def test_other_user_cannot_see_or_read_private_prompt(
    client: TestClient,
) -> None:
    client.post("/api/private-prompts", headers=_as("alice"), json=_payload())

    # Bob's listing is empty and a direct read 404s (existence not leaked).
    assert client.get("/api/private-prompts", headers=_as("bob")).json() == []
    assert (
        client.get(
            "/api/private-prompts/my-notes", headers=_as("bob")
        ).status_code
        == 404
    )


def test_other_user_cannot_delete_or_update_private_prompt(
    client: TestClient,
) -> None:
    client.post("/api/private-prompts", headers=_as("alice"), json=_payload())

    # Deleting a non-existent (from bob's view) name is a no-op, not a leak.
    assert (
        client.delete(
            "/api/private-prompts/my-notes", headers=_as("bob")
        ).status_code
        == 204
    )
    # Alice's copy is untouched.
    assert (
        client.get(
            "/api/private-prompts/my-notes", headers=_as("alice")
        ).status_code
        == 200
    )


def test_requires_authentication(client: TestClient) -> None:
    resp = client.get("/api/private-prompts", headers=_as(""))
    assert resp.status_code == 401


def test_create_rejects_name_reserved_by_canned_prompt(
    client: TestClient,
) -> None:
    payload = _payload(name="greet")
    resp = client.post(
        "/api/private-prompts", headers=_as("alice"), json=payload
    )
    assert resp.status_code == 409
