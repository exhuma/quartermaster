"""
Tests for the kit CRUD service layer (validate-before-commit).

These exercise ``app.services.kit_service`` against a temporary kits root.
The central guarantees are: a malformed write is rejected and leaves the
on-disk catalog untouched, and after any successful mutation the catalog
still loads through the existing read path (``app.kits``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import kits as kits_mod
from app.kits import (
    KitConflictError,
    KitNotFoundError,
    KitValidationError,
)
from app.services import kit_service as svc
from app.services.kit_service import SectionInput
from app.storage.kit_writes import KitPathError


@pytest.fixture()
def kits_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )
    return tmp_path


def _manifest(**overrides) -> dict:
    base = {
        "kit_type": "module",
        "summary": "A test kit.",
        "domains": ["testing"],
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
    }
    base.update(overrides)
    return base


def _sections() -> list[SectionInput]:
    return [
        SectionInput(
            file="invariant.md",
            title="Invariants",
            gloss="Core rules",
            always_load=True,
            body="# Invariants\n\nAlways do the right thing.\n",
        ),
        SectionInput(
            file="details.md",
            title="Details",
            gloss="The details",
            always_load=False,
            body="# Details\n\nMore text.\n",
        ),
    ]


def _ids(name: str = "module-test", version: str | None = None) -> list[str]:
    outline = kits_mod.read_kit_outline(name, version)
    return [s["id"] for s in outline["sections"]]


def _create(name: str = "module-test") -> dict:
    return svc.create_kit(
        name=name,
        applicability=_manifest(),
        summary="A test kit.",
        sections=_sections(),
        changelog="# Changelog\n\n## v1.0.0\n\nInitial.\n",
    )


# ---------------------------------------------------------------------------
# create_kit
# ---------------------------------------------------------------------------


def test_create_kit_round_trips_through_read_path(kits_root: Path) -> None:
    _create()
    names = [k["name"] for k in svc.list_kits()]
    assert "module-test" in names
    # The existing read path can load the freshly written kit.
    outline = kits_mod.read_kit_outline("module-test")
    assert outline["summary"] == "A test kit."
    assert [s["id"] for s in outline["sections"]] == ["invariant", "details"]
    assert "Always do the right thing" in kits_mod.read_kit("module-test")


def test_create_kit_rejects_invalid_manifest_without_writing(
    kits_root: Path,
) -> None:
    bad = _manifest(kit_type="bogus")
    with pytest.raises(KitValidationError):
        svc.create_kit(
            name="module-bad",
            applicability=bad,
            summary="x",
            sections=_sections(),
        )
    # Nothing was committed.
    assert not (kits_root / "module-bad").exists()
    assert "module-bad" not in [k["name"] for k in svc.list_kits()]


def test_create_kit_requires_a_section(kits_root: Path) -> None:
    with pytest.raises(KitValidationError):
        svc.create_kit(
            name="module-empty",
            applicability=_manifest(),
            summary="x",
            sections=[],
        )
    assert not (kits_root / "module-empty").exists()


def test_create_kit_conflict(kits_root: Path) -> None:
    _create()
    with pytest.raises(KitConflictError):
        _create()


def test_create_kit_rejects_unsafe_name(kits_root: Path) -> None:
    with pytest.raises(KitPathError):
        svc.create_kit(
            name="../evil",
            applicability=_manifest(),
            summary="x",
            sections=_sections(),
        )


# ---------------------------------------------------------------------------
# applicability
# ---------------------------------------------------------------------------


def test_replace_applicability(kits_root: Path) -> None:
    _create()
    updated = _manifest(priority=99, summary="Updated summary.")
    result = svc.replace_applicability("module-test", updated)
    assert result["priority"] == 99
    on_disk = json.loads(
        (kits_root / "module-test" / "applicability.json").read_text()
    )
    assert on_disk["priority"] == 99


def test_replace_applicability_invalid_keeps_original(kits_root: Path) -> None:
    _create()
    with pytest.raises(KitValidationError):
        svc.replace_applicability("module-test", _manifest(priority="high"))
    on_disk = svc.get_applicability("module-test")
    assert on_disk["priority"] == 50  # unchanged


def test_get_applicability_unknown_kit(kits_root: Path) -> None:
    with pytest.raises(KitNotFoundError):
        svc.get_applicability("module-missing")


# ---------------------------------------------------------------------------
# sections
# ---------------------------------------------------------------------------


def test_put_section_creates_and_updates(kits_root: Path) -> None:
    _create()
    # Create a new section.
    svc.put_section(
        "module-test",
        "v1",
        section_id="extra",
        title="Extra",
        gloss="More",
        always_load=False,
        body="# Extra\n\nNew.\n",
    )
    assert _ids() == ["invariant", "details", "extra"]
    # Update the same section in place (order preserved).
    svc.put_section(
        "module-test",
        "v1",
        section_id="extra",
        title="Extra v2",
        gloss="More",
        always_load=True,
        body="# Extra\n\nChanged.\n",
    )
    got = svc.get_section("module-test", "v1", "extra")
    assert got["title"] == "Extra v2"
    assert got["always_load"] is True
    assert "Changed." in got["body"]
    assert _ids() == ["invariant", "details", "extra"]  # no duplicate


def test_delete_section(kits_root: Path) -> None:
    _create()
    remaining = svc.delete_section("module-test", "v1", "details")
    assert remaining == ["invariant"]
    assert kits_mod.read_kit("module-test")  # still loads


def test_delete_last_section_rejected_and_original_intact(
    kits_root: Path,
) -> None:
    _create()
    svc.delete_section("module-test", "v1", "details")
    # Removing the final section would empty the index -> rejected.
    with pytest.raises(KitValidationError):
        svc.delete_section("module-test", "v1", "invariant")
    # The kit still loads with its remaining section.
    assert _ids() == ["invariant"]


def test_delete_absent_section_is_noop(kits_root: Path) -> None:
    _create()
    remaining = svc.delete_section("module-test", "v1", "nope")
    assert remaining == ["invariant", "details"]


def test_put_section_with_quotes_in_title(kits_root: Path) -> None:
    # Titles with quotes must survive the hand-rolled TOML emitter.
    _create()
    svc.put_section(
        "module-test",
        "v1",
        section_id="quoted",
        title='He said "hi" \\ ok',
        gloss="g",
        always_load=False,
        body="x\n",
    )
    outline = kits_mod.read_kit_outline("module-test")
    titles = {s["id"]: s["title"] for s in outline["sections"]}
    assert titles["quoted"] == 'He said "hi" \\ ok'


# ---------------------------------------------------------------------------
# versions
# ---------------------------------------------------------------------------


def test_create_and_delete_version(kits_root: Path) -> None:
    _create()
    versions = svc.create_version(
        "module-test",
        "v2",
        summary="Second major.",
        sections=[
            SectionInput(
                file="invariant.md",
                title="Invariants",
                gloss="g",
                always_load=True,
                body="# v2\n",
            )
        ],
    )
    assert versions == ["v1", "v2"]
    assert "# v2" in kits_mod.read_kit("module-test", "v2")
    # Latest resolves to v2.
    assert svc.get_kit_detail("module-test")["latest_version"] == "v2"
    remaining = svc.delete_version("module-test", "v2")
    assert remaining == ["v1"]


def test_create_version_conflict(kits_root: Path) -> None:
    _create()
    with pytest.raises(KitConflictError):
        svc.create_version(
            "module-test", "v1", summary="dup", sections=_sections()
        )


def test_create_version_unknown_kit(kits_root: Path) -> None:
    with pytest.raises(KitNotFoundError):
        svc.create_version(
            "module-ghost", "v2", summary="x", sections=_sections()
        )


# ---------------------------------------------------------------------------
# delete_kit
# ---------------------------------------------------------------------------


def test_delete_kit_idempotent(kits_root: Path) -> None:
    _create()
    svc.delete_kit("module-test")
    assert "module-test" not in [k["name"] for k in svc.list_kits()]
    # Second delete is a no-op, not an error.
    svc.delete_kit("module-test")


# ---------------------------------------------------------------------------
# HTTP router (auth-free app to isolate routing + status mapping)
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(kits_root: Path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.main import _register_exception_handlers
    from app.media_types import VENDOR_MEDIA_TYPE
    from app.routers import kits_admin

    app = FastAPI()
    app.include_router(kits_admin.router)
    _register_exception_handlers(app)
    # The router enforces the vendor Accept type; send it by default.
    return TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


def _create_payload(name: str = "module-test") -> dict:
    return {
        "name": name,
        "applicability": _manifest(),
        "summary": "A test kit.",
        "sections": [
            {
                "file": "invariant.md",
                "title": "Invariants",
                "gloss": "Core rules",
                "always_load": True,
                "body": "# Invariants\n\nText.\n",
            }
        ],
    }


def test_api_create_list_get_delete(client) -> None:
    resp = client.post("/api/kits", json=_create_payload())
    assert resp.status_code == 201, resp.text
    assert "module-test" in [k["name"] for k in client.get("/api/kits").json()]
    assert client.get("/api/kits/module-test").json()["latest_version"] == "v1"
    assert client.delete("/api/kits/module-test").status_code == 204
    assert client.get("/api/kits/module-test").status_code == 404


def test_api_create_conflict(client) -> None:
    client.post("/api/kits", json=_create_payload())
    assert client.post("/api/kits", json=_create_payload()).status_code == 409


def test_api_create_invalid_manifest_is_422(client) -> None:
    payload = _create_payload()
    payload["applicability"]["kit_type"] = "nonsense"
    assert client.post("/api/kits", json=payload).status_code == 422


def test_api_put_and_get_section(client) -> None:
    client.post("/api/kits", json=_create_payload())
    resp = client.put(
        "/api/kits/module-test/versions/v1/sections/extra",
        json={
            "title": "Extra",
            "gloss": "g",
            "always_load": False,
            "body": "# Extra\n",
        },
    )
    assert resp.status_code == 200, resp.text
    got = client.get("/api/kits/module-test/versions/v1/sections/extra").json()
    assert "Extra" in got["body"]


def test_api_unknown_kit_is_404(client) -> None:
    assert client.get("/api/kits/module-ghost").status_code == 404


def test_api_traits_endpoint(client) -> None:
    _create()
    body = client.get("/api/traits").json()
    assert "languages" in body
    assert "kit_types" in body
    assert "python" in body["languages"]  # from the created kit's manifest


def test_api_outline_changelog_applicability(client) -> None:
    client.post("/api/kits", json=_create_payload())
    outline = client.get(
        "/api/kits/module-test/versions/v1/outline"
    ).json()
    assert [s["id"] for s in outline["sections"]] == ["invariant"]
    cl = client.get("/api/kits/module-test/changelog").json()
    assert "changelog" in cl
    app = client.get("/api/kits/module-test/applicability").json()
    assert app["kit_type"] == "module"


def test_api_compare_versions(client) -> None:
    client.post("/api/kits", json=_create_payload())
    client.post(
        "/api/kits/module-test/versions",
        json={
            "version": "v2",
            "summary": "Second.",
            "sections": [
                {
                    "file": "invariant.md",
                    "title": "Invariants",
                    "gloss": "g",
                    "always_load": True,
                    "body": "# v2\n",
                }
            ],
        },
    )
    resp = client.get("/api/kits/module-test/compare?from=v1&to=v2")
    assert resp.status_code == 200
    assert "user_facing_warning" in resp.json()


def test_api_response_uses_vendor_content_type(client) -> None:
    from app.media_types import VENDOR_MEDIA_TYPE

    resp = client.get("/api/kits")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == VENDOR_MEDIA_TYPE


def test_api_rejects_plain_json_accept(client) -> None:
    resp = client.get("/api/kits", headers={"Accept": "application/json"})
    assert resp.status_code == 406
    assert "vnd.instructions" in resp.json()["detail"]


def test_api_rejects_wildcard_accept(client) -> None:
    resp = client.get("/api/kits", headers={"Accept": "*/*"})
    assert resp.status_code == 406
