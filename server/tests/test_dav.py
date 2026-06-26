"""
Integration tests for the WebDAV authoring endpoint and its Basic gate.

Builds the full app via create_app with env pointing at a temporary kit
catalog, so the wsgidav provider and the JWTAuthMiddleware Basic→app-token
flow are exercised end to end.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.storage import app_tokens


@pytest.fixture()
def dav(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    kits = tmp_path / "kits"
    instr = kits / "module-x" / "v1" / "instructions"
    instr.mkdir(parents=True)
    (instr / "invariant.md").write_text("# hi\n", encoding="utf-8")
    tokens = tmp_path / "tokens.json"

    for key, value in {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(kits),
        "APP_TOKENS_PATH": str(tokens),
        "DAV_REQUIRE_TLS": "false",
        "WEBUI_DIST": "/nonexistent",
    }.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()

    from app.main import create_app

    client = TestClient(create_app())
    _, token = app_tokens.mint(tokens, "alice", "test")
    yield client, token, kits
    get_settings.cache_clear()


def test_dav_requires_credentials(dav) -> None:
    client, _token, _kits = dav
    resp = client.get("/dav/module-x/v1/instructions/invariant.md")
    assert resp.status_code == 401
    assert resp.headers["WWW-Authenticate"].startswith("Basic")


def test_dav_rejects_bad_token(dav) -> None:
    client, _token, _kits = dav
    resp = client.get(
        "/dav/module-x/v1/instructions/invariant.md",
        auth=("alice", "not-a-real-token"),
    )
    assert resp.status_code == 401


def test_dav_get_with_valid_token(dav) -> None:
    client, token, _kits = dav
    resp = client.get(
        "/dav/module-x/v1/instructions/invariant.md",
        auth=("alice", token),
    )
    assert resp.status_code == 200
    assert "# hi" in resp.text


def test_dav_put_lands_on_kits_root(dav) -> None:
    client, token, kits = dav
    target = "/dav/module-x/v1/instructions/new.md"
    resp = client.put(target, content="# new section\n", auth=("alice", token))
    assert resp.status_code in (200, 201, 204), resp.text
    # The write landed on the same kits_root the MCP reads.
    on_disk = kits / "module-x" / "v1" / "instructions" / "new.md"
    assert on_disk.read_text() == "# new section\n"


def test_dav_propfind_lists_collection(dav) -> None:
    client, token, _kits = dav
    resp = client.request(
        "PROPFIND",
        "/dav/module-x/v1/instructions/",
        headers={"Depth": "1"},
        auth=("alice", token),
    )
    assert resp.status_code == 207  # Multi-Status
    assert "invariant.md" in resp.text


def test_dav_propfind_hrefs_carry_mount_prefix(dav) -> None:
    """
    PROPFIND hrefs must be prefixed with the ``/dav`` mount path.

    wsgidav is mounted under ``/dav`` by FastAPI; without ``mount_path`` it
    emits root-relative hrefs (``/module-x/...``) that clients such as
    davfs2 discard as outside the requested collection, so existing kits
    never show up in ``ls`` even though writes succeed. Regression guard.
    """
    client, token, _kits = dav
    resp = client.request(
        "PROPFIND",
        "/dav/module-x/v1/instructions/",
        headers={"Depth": "1"},
        auth=("alice", token),
    )
    assert resp.status_code == 207
    hrefs = re.findall(r"<[^>]*href>([^<]*)</[^>]*href>", resp.text, re.I)
    assert hrefs, "PROPFIND returned no hrefs"
    for href in hrefs:
        assert href.startswith("/dav/"), f"href missing /dav prefix: {href}"
    # The collection itself and its child are both present and prefixed.
    assert "/dav/module-x/v1/instructions/" in hrefs
    assert "/dav/module-x/v1/instructions/invariant.md" in hrefs


def test_dav_requires_tls_when_configured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    kits = tmp_path / "kits"
    kits.mkdir()
    tokens = tmp_path / "tokens.json"
    for key, value in {
        "KEYCLOAK_URL": "https://auth.example.com",
        "KEYCLOAK_REALM": "master",
        "RESOURCE_BASE_URL": "https://x.example.com",
        "KITS_ROOT": str(kits),
        "APP_TOKENS_PATH": str(tokens),
        "DAV_REQUIRE_TLS": "true",
        "WEBUI_DIST": "/nonexistent",
    }.items():
        monkeypatch.setenv(f"QM_{key}", value)
    get_settings.cache_clear()
    from app.main import create_app

    client = TestClient(create_app())
    _, token = app_tokens.mint(tokens, "alice")
    # Plain HTTP (TestClient) is refused when TLS is required.
    resp = client.get("/dav/", auth=("alice", token))
    assert resp.status_code == 403
    get_settings.cache_clear()
