"""Tests for the GET/DELETE /api/me/memory endpoints."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from app.storage import user_memory


@pytest.fixture()
def memory_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from app.media_types import VENDOR_MEDIA_TYPE
    from app.routers import me as router_mod

    path = tmp_path / "user-memory.toml"
    monkeypatch.setattr(
        router_mod,
        "get_settings",
        lambda: SimpleNamespace(user_memory_store_path=path),
    )

    class FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.auth_sub = "alice"
            return await call_next(request)

    app = FastAPI()
    app.include_router(router_mod.router)
    app.add_middleware(FakeAuth)
    client = TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})
    return client, path


def test_get_memory_returns_empty_profile_when_none_derived(
    memory_client,
) -> None:
    client, _ = memory_client
    resp = client.get("/api/me/memory")
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] is None
    assert body["top_kits"] == []


def test_get_memory_returns_stored_profile(memory_client) -> None:
    client, path = memory_client
    user_memory.save_profile(
        path,
        "alice",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": ["auth"],
            "top_kits": ["module-auth-oidc"],
            "top_languages": ["python"],
            "top_frameworks": [],
        },
    )
    resp = client.get("/api/me/memory")
    assert resp.json()["top_kits"] == ["module-auth-oidc"]


def test_get_memory_scoped_to_caller(memory_client) -> None:
    client, path = memory_client
    user_memory.save_profile(
        path,
        "bob",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": [],
            "top_kits": ["module-bob-only"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    resp = client.get("/api/me/memory")
    assert resp.json()["top_kits"] == []


def test_delete_memory_clears_and_is_idempotent(memory_client) -> None:
    client, path = memory_client
    user_memory.save_profile(
        path,
        "alice",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": [],
            "top_kits": ["module-auth-oidc"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    resp = client.delete("/api/me/memory")
    assert resp.status_code == 204
    assert client.get("/api/me/memory").json()["top_kits"] == []
    # Idempotent: deleting again still succeeds.
    resp2 = client.delete("/api/me/memory")
    assert resp2.status_code == 204


def test_delete_memory_does_not_affect_other_subjects(memory_client) -> None:
    client, path = memory_client
    user_memory.save_profile(
        path,
        "bob",
        {
            "updated": "2026-01-01T00:00:00+00:00",
            "top_domains": [],
            "top_kits": ["module-bob-only"],
            "top_languages": [],
            "top_frameworks": [],
        },
    )
    client.delete("/api/me/memory")
    assert user_memory.load_profile(path, "bob")["top_kits"] == [
        "module-bob-only"
    ]
