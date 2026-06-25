"""
Tests for the per-user WebDAV app-token registry.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from starlette.middleware.base import BaseHTTPMiddleware

from app.storage import app_tokens


def test_mint_returns_plaintext_once_and_stores_hash(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    record, token = app_tokens.mint(path, "alice", "laptop")
    assert token  # plaintext returned
    assert "token_hash" not in record  # public record hides the secret
    # The raw file stores only the hash, never the plaintext.
    assert token not in path.read_text()


def test_verify_matches_only_the_right_token(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    _, token = app_tokens.mint(path, "alice")
    assert app_tokens.verify(path, token)["user"] == "alice"
    assert app_tokens.verify(path, "wrong") is None
    assert app_tokens.verify(path, "") is None


def test_list_is_scoped_to_user(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    app_tokens.mint(path, "alice", "a")
    app_tokens.mint(path, "bob", "b")
    alice = app_tokens.list_for(path, "alice")
    assert len(alice) == 1
    assert alice[0]["user"] == "alice"
    assert "token_hash" not in alice[0]


def test_revoke_only_own_token(tmp_path: Path) -> None:
    path = tmp_path / "tokens.json"
    record, token = app_tokens.mint(path, "alice")
    # Another user cannot revoke it.
    assert app_tokens.revoke(path, record["id"], "bob") is False
    assert app_tokens.verify(path, token) is not None
    # The owner can.
    assert app_tokens.revoke(path, record["id"], "alice") is True
    assert app_tokens.verify(path, token) is None
    # Idempotent.
    assert app_tokens.revoke(path, record["id"], "alice") is False


# ---------------------------------------------------------------------------
# Router (with a stand-in auth middleware that sets request.state)
# ---------------------------------------------------------------------------


@pytest.fixture()
def token_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from fastapi.testclient import TestClient

    from app.media_types import VENDOR_MEDIA_TYPE
    from app.routers import app_tokens as router_mod

    path = tmp_path / "tokens.json"
    monkeypatch.setattr(
        router_mod,
        "get_settings",
        lambda: SimpleNamespace(app_tokens_path=path),
    )

    class FakeAuth(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            request.state.auth_subject = "alice"
            return await call_next(request)

    app = FastAPI()
    app.include_router(router_mod.router)
    app.add_middleware(FakeAuth)
    return TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


def test_router_mint_list_revoke(token_client) -> None:
    minted = token_client.post("/api/app-tokens", json={"label": "laptop"})
    assert minted.status_code == 201
    body = minted.json()
    assert body["token"]  # plaintext returned once
    assert body["user"] == "alice"

    listed = token_client.get("/api/app-tokens").json()
    assert len(listed) == 1
    assert "token" not in listed[0]  # never list the secret

    assert (
        token_client.delete(f"/api/app-tokens/{body['id']}").status_code
        == 204
    )
    assert token_client.get("/api/app-tokens").json() == []
