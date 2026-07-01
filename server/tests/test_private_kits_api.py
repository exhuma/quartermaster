"""Integration tests for the owner-scoped ``/api/private-kits`` router."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import get_settings
from app.media_types import VENDOR_MEDIA_TYPE


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    for key, value in {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(tmp_path / "kits"),
        "PRIVATE_KITS_ROOT": str(tmp_path / "private"),
    }.items():
        monkeypatch.setenv(f"QM_{key}", value)
    (tmp_path / "kits").mkdir()
    get_settings.cache_clear()

    from app.main import _register_exception_handlers
    from app.routers import private_kits

    app = FastAPI()

    @app.middleware("http")
    async def _stamp_identity(request: Request, call_next):  # noqa: ANN001
        request.state.auth_sub = request.headers.get("X-Test-Sub", "")
        return await call_next(request)

    app.include_router(private_kits.router)
    _register_exception_handlers(app)
    yield TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})
    get_settings.cache_clear()


def _payload(name: str = "my-notes") -> dict:
    return {
        "name": name,
        "applicability": {
            "kit_type": "module",
            "summary": "Private notes.",
            "domains": ["personal"],
            "languages": ["python"],
            "frameworks": [],
            "contexts": ["backend"],
            "requires": {
                "languages": [],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
            "excludes": {
                "languages": [],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
            "optional_signals": [],
            "related_kits": [],
            "priority": 50,
        },
        "summary": "Private notes.",
        "sections": [
            {
                "file": "invariant.md",
                "title": "Invariants",
                "gloss": "Core rules",
                "always_load": True,
                "body": "# Invariants\n\nSecret.\n",
            }
        ],
    }


def _as(sub: str) -> dict[str, str]:
    return {"X-Test-Sub": sub}


def test_create_list_get_delete_own_private_kit(client: TestClient) -> None:
    created = client.post("/api/private-kits", headers=_as("alice"), json=_payload())
    assert created.status_code == 201, created.text
    assert created.headers["Location"] == "/api/private-kits/my-notes"

    listing = client.get("/api/private-kits", headers=_as("alice"))
    assert [k["name"] for k in listing.json()] == ["my-notes"]

    detail = client.get("/api/private-kits/my-notes", headers=_as("alice"))
    assert detail.status_code == 200
    assert detail.json()["latest_version"] == "v1"

    gone = client.delete("/api/private-kits/my-notes", headers=_as("alice"))
    assert gone.status_code == 204
    assert client.get("/api/private-kits", headers=_as("alice")).json() == []


def test_other_user_cannot_see_or_read_private_kit(client: TestClient) -> None:
    client.post("/api/private-kits", headers=_as("alice"), json=_payload())

    # Bob's listing is empty and a direct read 404s (existence not leaked).
    assert client.get("/api/private-kits", headers=_as("bob")).json() == []
    assert (
        client.get("/api/private-kits/my-notes", headers=_as("bob")).status_code
        == 404
    )


def test_requires_authentication(client: TestClient) -> None:
    resp = client.get("/api/private-kits", headers=_as(""))
    assert resp.status_code == 401
