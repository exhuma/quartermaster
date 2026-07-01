"""Integration tests for role-based write authorization over HTTP.

Routers are mounted on a bare app (no JWT middleware) with a small middleware
that stamps ``request.state.auth_sub`` from a test header, so each request can
act as a chosen subject. Settings (role store path + bootstrap editors) come
from the environment, exactly as in production.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import get_settings
from app.media_types import VENDOR_MEDIA_TYPE
from app.routers import kits_admin
from app.routers import me as me_router
from app.routers import roles as roles_router
from app.storage import role_store


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "ROLE_STORE_PATH": str(tmp_path / "roles.toml"),
        "INITIAL_EDITORS": "boss-sub",
    }.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()

    app = FastAPI()

    @app.middleware("http")
    async def _stamp_identity(request: Request, call_next):  # noqa: ANN001
        sub = request.headers.get("X-Test-Sub", "")
        request.state.auth_sub = sub
        request.state.auth_label = sub
        return await call_next(request)

    app.include_router(kits_admin.router)
    app.include_router(me_router.router)
    app.include_router(roles_router.router)
    # Reuse the production exception→status mapping so authz/validation
    # exceptions surface as 403/422 rather than 500.
    from app.main import _register_exception_handlers

    _register_exception_handlers(app)
    yield TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})
    get_settings.cache_clear()


def _as(sub: str) -> dict[str, str]:
    return {"X-Test-Sub": sub}


def test_me_reports_consumer_by_default(client: TestClient) -> None:
    resp = client.get("/api/me", headers=_as("nobody"))
    assert resp.status_code == 200
    assert resp.json() == {"sub": "nobody", "label": "nobody", "role": "consumer"}


def test_me_reports_bootstrap_editor(client: TestClient) -> None:
    resp = client.get("/api/me", headers=_as("boss-sub"))
    assert resp.json()["role"] == "editor"


def test_consumer_cannot_create_kit(client: TestClient) -> None:
    resp = client.post(
        "/api/kits",
        headers=_as("consumer-1"),
        json={
            "name": "should-not-exist",
            "applicability": {},
            "summary": "x",
            "sections": [],
        },
    )
    assert resp.status_code == 403
    assert "editor" in resp.json()["detail"].lower()


def test_consumer_cannot_list_roles(client: TestClient) -> None:
    resp = client.get("/api/roles", headers=_as("consumer-1"))
    assert resp.status_code == 403


def test_editor_can_grant_and_revoke_editor(client: TestClient) -> None:
    # Bootstrap editor promotes a new user.
    put = client.put(
        "/api/roles/new-editor",
        headers=_as("boss-sub"),
        json={"role": "editor", "label": "New Editor"},
    )
    assert put.status_code == 200
    assert put.json()["role"] == "editor"

    # The promoted user is now an editor and can list roles.
    listing = client.get("/api/roles", headers=_as("new-editor"))
    assert listing.status_code == 200
    subs = {r["sub"] for r in listing.json()}
    assert {"boss-sub", "new-editor"} <= subs

    # Revoke reverts them to consumer.
    delete = client.delete("/api/roles/new-editor", headers=_as("boss-sub"))
    assert delete.status_code == 204
    after = client.get("/api/me", headers=_as("new-editor"))
    assert after.json()["role"] == "consumer"


def test_bootstrap_editor_cannot_be_revoked_over_http(
    client: TestClient,
) -> None:
    resp = client.delete("/api/roles/boss-sub", headers=_as("boss-sub"))
    assert resp.status_code == 422


def test_unknown_role_is_rejected(client: TestClient) -> None:
    resp = client.put(
        "/api/roles/someone",
        headers=_as("boss-sub"),
        json={"role": "superuser"},
    )
    assert resp.status_code == 422


def test_role_store_persists_to_toml(client: TestClient) -> None:
    client.put(
        "/api/roles/persisted",
        headers=_as("boss-sub"),
        json={"role": "editor"},
    )
    path = get_settings().role_store_path
    assert role_store.get_role(path, "persisted") == "editor"
