"""
Tests for multi-root kit layer support.

Covers:
- Two-layer discovery: overlay shadows base; base-only kit still appears
- Binding section merge: base binding section contributed into overlay's view
- Layer REST endpoints (GET/POST/DELETE per-layer)
- Readonly enforcement (403 on write to readonly layer)
- Backward compat: single QM_KITS_ROOT → layer "default"
- Config validation (no root → error; all-readonly → error)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.config import KitLayerConfig, Settings, load_layers_from_toml
from app.kits import (
    KitLayerNotFoundError,
    KitLayerReadonlyError,
    KitNotFoundError,
    _get_effective_layers,
    _kit_version_paths_layered,
    _resolve_merged_kit,
    list_all_kits,
    read_kit,
    read_kit_outline,
)
from app.services import kit_service as svc
from app.services.kit_service import _layer_path, _layer_write_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_APPLICABILITY: dict = {
    "kit_type": "module",
    "summary": "Test kit applicability",
    "domains": ["testing"],
    "languages": ["python"],
    "frameworks": [],
    "contexts": [],
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


def _make_kit(root: Path, name: str, binding: bool = False) -> None:
    """
    Create a minimal valid kit under *root* using the current catalog format.
    """
    instr_dir = root / name / "v1" / "instructions"
    instr_dir.mkdir(parents=True, exist_ok=True)
    body = f"# {name}\n\nKit body."
    (instr_dir / "invariant.md").write_text(body, encoding="utf-8")
    binding_flag = "true" if binding else "false"
    (instr_dir / "index.toml").write_text(
        f'summary = "Summary for {name}"\n\n'
        f"[[sections]]\n"
        f'file = "invariant.md"\n'
        f'title = "Core"\n'
        f'gloss = "Core invariants"\n'
        f"always_load = true\n"
        f"binding = {binding_flag}\n",
        encoding="utf-8",
    )
    (root / name / "applicability.json").write_text(
        json.dumps(_APPLICABILITY), encoding="utf-8"
    )
    (root / name / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.0.0\n\nInitial.\n", encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_effective_layers_from_kits_root(tmp_path: Path) -> None:
    """Single QM_KITS_ROOT maps to a single default layer."""
    mock = type("S", (), {"kits_root": tmp_path})()
    mock.effective_layers = [
        KitLayerConfig(name="default", path=tmp_path, readonly=False)
    ]
    layers = _get_effective_layers(mock)
    assert len(layers) == 1
    assert layers[0].name == "default"
    assert layers[0].path == tmp_path
    assert layers[0].readonly is False


def test_get_effective_layers_fallback_for_kits_root_mock(
    tmp_path: Path,
) -> None:
    """_get_effective_layers handles test mocks with only kits_root."""
    mock = type("S", (), {"kits_root": tmp_path})()
    layers = _get_effective_layers(mock)
    assert len(layers) == 1
    assert layers[0].path == tmp_path


# ---------------------------------------------------------------------------
# TOML layers file loader
# ---------------------------------------------------------------------------


def test_load_layers_from_toml_basic(tmp_path: Path) -> None:
    """A well-formed TOML file parses into ordered KitLayerConfig entries."""
    (tmp_path / "company").mkdir()
    (tmp_path / "team").mkdir()
    toml_file = tmp_path / "layers.toml"
    toml_file.write_text(
        "[[layer]]\n"
        'name = "company"\n'
        'path = "/abs/company"\n'
        "readonly = true\n\n"
        "[[layer]]\n"
        'name = "team"\n'
        'path = "/abs/team"\n',
        encoding="utf-8",
    )
    layers = load_layers_from_toml(toml_file)
    assert [l.name for l in layers] == ["company", "team"]
    assert layers[0].readonly is True
    assert layers[1].readonly is False
    assert layers[0].path == Path("/abs/company")


def test_load_layers_relative_paths_resolved_against_file_dir(
    tmp_path: Path,
) -> None:
    """Relative layer paths resolve against the TOML file's directory."""
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    toml_file = cfg_dir / "layers.toml"
    toml_file.write_text(
        "[[layer]]\n"
        'name = "base"\n'
        'path = "catalogs/base"\n',
        encoding="utf-8",
    )
    layers = load_layers_from_toml(toml_file)
    assert layers[0].path == (cfg_dir / "catalogs" / "base").resolve()


def test_load_layers_missing_file_raises(tmp_path: Path) -> None:
    """A missing TOML file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_layers_from_toml(tmp_path / "nope.toml")


def test_load_layers_empty_raises(tmp_path: Path) -> None:
    """A TOML file with no [[layer]] entries raises ValueError."""
    toml_file = tmp_path / "layers.toml"
    toml_file.write_text("# no layers here\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_layers_from_toml(toml_file)


def test_load_layers_missing_fields_raises(tmp_path: Path) -> None:
    """A [[layer]] missing name or path raises ValueError."""
    toml_file = tmp_path / "layers.toml"
    toml_file.write_text(
        '[[layer]]\nname = "base"\n', encoding="utf-8"
    )
    with pytest.raises(ValueError):
        load_layers_from_toml(toml_file)


def test_load_layers_duplicate_name_raises(tmp_path: Path) -> None:
    """Duplicate layer names raise ValueError."""
    toml_file = tmp_path / "layers.toml"
    toml_file.write_text(
        '[[layer]]\nname = "dup"\npath = "/a"\n\n'
        '[[layer]]\nname = "dup"\npath = "/b"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_layers_from_toml(toml_file)


def test_settings_kit_layers_file_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """kit_layers_file wins over kits_root in Settings."""
    file_layer_dir = tmp_path / "from-file"
    file_layer_dir.mkdir()
    toml_file = tmp_path / "layers.toml"
    toml_file.write_text(
        "[[layer]]\n"
        'name = "from-file"\n'
        'path = "from-file"\n',
        encoding="utf-8",
    )
    # Required base settings for a constructable Settings object.
    monkeypatch.setenv("QM_KEYCLOAK_URL", "https://auth.example.com")
    monkeypatch.setenv("QM_KEYCLOAK_REALM", "master")
    monkeypatch.setenv("QM_RESOURCE_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("QM_KITS_ROOT", str(tmp_path / "ignored-root"))
    monkeypatch.setenv("QM_KIT_LAYERS_FILE", str(toml_file))

    settings = Settings()  # type: ignore[call-arg]
    layers = settings.effective_layers
    assert [l.name for l in layers] == ["from-file"]
    assert layers[0].path == file_layer_dir.resolve()


def test_settings_kit_layers_file_all_readonly_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A layers file with every layer readonly is rejected at validation."""
    import pydantic

    toml_file = tmp_path / "layers.toml"
    toml_file.write_text(
        "[[layer]]\n"
        'name = "ro"\n'
        'path = "/a"\n'
        "readonly = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("QM_KEYCLOAK_URL", "https://auth.example.com")
    monkeypatch.setenv("QM_KEYCLOAK_REALM", "master")
    monkeypatch.setenv("QM_RESOURCE_BASE_URL", "http://localhost:8000")
    monkeypatch.delenv("QM_KITS_ROOT", raising=False)
    monkeypatch.setenv("QM_KIT_LAYERS_FILE", str(toml_file))

    with pytest.raises(pydantic.ValidationError):
        Settings()  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Discovery: shadowing and merged view
# ---------------------------------------------------------------------------


def test_overlay_shadows_base_kit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When overlay has the same kit name, it shadows the base entirely."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    _make_kit(base, "shared-kit")
    _make_kit(overlay, "shared-kit")

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    kits = list_all_kits()
    assert len(kits) == 1
    kit = kits[0]
    assert kit.name == "shared-kit"
    assert kit.source_layer == "overlay"


def test_base_only_kit_still_appears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A kit that exists only in the base layer is visible in the merged view."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    _make_kit(base, "base-only-kit")
    _make_kit(overlay, "overlay-only-kit")

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    kit_names = {k.name for k in list_all_kits()}
    assert "base-only-kit" in kit_names
    assert "overlay-only-kit" in kit_names
    assert len(kit_names) == 2


def test_source_layer_assigned_correctly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """source_layer is the highest-priority layer that contains each kit."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    _make_kit(base, "base-kit")
    _make_kit(base, "shared-kit")
    _make_kit(overlay, "shared-kit")
    _make_kit(overlay, "overlay-kit")

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    by_name = {k.name: k for k in list_all_kits()}
    assert by_name["base-kit"].source_layer == "base"
    assert by_name["shared-kit"].source_layer == "overlay"
    assert by_name["overlay-kit"].source_layer == "overlay"


# ---------------------------------------------------------------------------
# Binding section merge
# ---------------------------------------------------------------------------


def test_binding_section_contributed_from_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Binding section from base layer is included even when overlay shadows kit."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    # Base has binding section
    _make_kit(base, "guarded-kit", binding=True)

    # Overlay also has this kit but with its own (non-binding) section
    overlay_instr = overlay / "guarded-kit" / "v1" / "instructions"
    overlay_instr.mkdir(parents=True)
    (overlay_instr / "extra.md").write_text("# Extra\n\nNew content.", encoding="utf-8")
    (overlay_instr / "index.toml").write_text(
        'summary = "Overlay guarded-kit"\n\n'
        "[[sections]]\n"
        'file = "extra.md"\n'
        'title = "Extra"\n'
        'gloss = "Extra section"\n'
        "always_load = false\n"
        "binding = false\n",
        encoding="utf-8",
    )
    (overlay / "guarded-kit" / "applicability.json").write_text(
        json.dumps(_APPLICABILITY), encoding="utf-8"
    )
    (overlay / "guarded-kit" / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.0.0\n\nInitial.\n", encoding="utf-8"
    )

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    outline = read_kit_outline("guarded-kit")
    section_ids = [s["id"] for s in outline["sections"]]
    # Binding base section "invariant" should appear along with overlay "extra"
    assert "invariant" in section_ids
    assert "extra" in section_ids

    # The binding section should be marked as such
    binding_section = next(s for s in outline["sections"] if s["id"] == "invariant")
    assert binding_section["binding"] is True


def test_non_binding_section_not_contributed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-binding base sections are NOT contributed when overlay shadows."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    # Base has non-binding section
    _make_kit(base, "normal-kit", binding=False)
    # Overlay shadows it with different content
    _make_kit(overlay, "normal-kit", binding=False)

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    outline = read_kit_outline("normal-kit")
    # Only overlay's sections (no duplication from base)
    section_ids = [s["id"] for s in outline["sections"]]
    assert section_ids.count("invariant") == 1


def test_binding_section_content_from_base_instr_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Content of a binding section is read from the base layer's file."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    # Base: binding section with distinctive content
    instr_dir = base / "binding-kit" / "v1" / "instructions"
    instr_dir.mkdir(parents=True)
    (instr_dir / "policy.md").write_text(
        "COMPANY POLICY — DO NOT OVERRIDE.", encoding="utf-8"
    )
    (instr_dir / "index.toml").write_text(
        'summary = "Binding kit"\n\n'
        "[[sections]]\n"
        'file = "policy.md"\n'
        'title = "Policy"\n'
        'gloss = "Binding company policy"\n'
        "always_load = true\n"
        "binding = true\n",
        encoding="utf-8",
    )
    (base / "binding-kit" / "applicability.json").write_text(
        json.dumps(_APPLICABILITY), encoding="utf-8"
    )
    (base / "binding-kit" / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.0.0\n\nInitial.\n", encoding="utf-8"
    )

    # Overlay: shadows with different content
    _make_kit(overlay, "binding-kit", binding=False)

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    content = read_kit("binding-kit", sections=["policy"])
    assert "COMPANY POLICY" in content


# ---------------------------------------------------------------------------
# Layer service helpers
# ---------------------------------------------------------------------------


def test_layer_path_resolves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_layer_path returns the path for a named layer."""
    base = tmp_path / "base"
    base.mkdir()
    layers = [KitLayerConfig(name="base", path=base, readonly=True)]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )
    assert _layer_path("base") == base


def test_layer_path_unknown_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_layer_path raises KitLayerNotFoundError for an unknown layer name."""
    layers = [
        KitLayerConfig(name="base", path=tmp_path, readonly=True)
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )
    with pytest.raises(KitLayerNotFoundError):
        _layer_path("nonexistent")


def test_layer_write_path_blocks_readonly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_layer_write_path raises KitLayerReadonlyError for readonly layers."""
    layers = [
        KitLayerConfig(name="company", path=tmp_path, readonly=True)
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )
    with pytest.raises(KitLayerReadonlyError):
        _layer_write_path("company")


# ---------------------------------------------------------------------------
# Service write operations targeting specific layers
# ---------------------------------------------------------------------------


def test_create_kit_in_specific_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_kit with explicit root writes only to the given root."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    detail = svc.create_kit(
        name="new-kit",
        applicability=_APPLICABILITY,
        summary="New kit summary",
        sections=[
            svc.SectionInput(
                file="invariant.md",
                title="Core",
                gloss="Core invariants",
                always_load=True,
                body="# Core\n\nInvariants.",
            )
        ],
        root=overlay,
    )
    assert detail["name"] == "new-kit"
    # Only overlay has the kit
    assert (overlay / "new-kit").is_dir()
    assert not (base / "new-kit").exists()


def test_delete_kit_from_specific_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """delete_kit with explicit root deletes only from that root."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    _make_kit(base, "shared-kit")
    _make_kit(overlay, "shared-kit")

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    svc.delete_kit("shared-kit", root=overlay)
    # Overlay copy is gone; base copy remains
    assert not (overlay / "shared-kit").exists()
    assert (base / "shared-kit").is_dir()


def test_write_default_root_uses_writable_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Writes without explicit root go to the last non-readonly layer."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S",
            (),
            {
                "kits_root": None,
                "effective_layers": layers,
            },
        )(),
    )

    svc.create_kit(
        name="auto-routed",
        applicability=_APPLICABILITY,
        summary="Auto-routed kit",
        sections=[
            svc.SectionInput(
                file="invariant.md",
                title="Core",
                gloss="Core invariants",
                always_load=True,
                body="# Core\n\nBody.",
            )
        ],
    )
    # Should land in overlay (the last writable layer)
    assert (overlay / "auto-routed").is_dir()
    assert not (base / "auto-routed").exists()


# ---------------------------------------------------------------------------
# Backward compat: single QM_KITS_ROOT
# ---------------------------------------------------------------------------


def test_single_root_compat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Single kits_root mock still works as a 'default' layer."""
    _make_kit(tmp_path, "compat-kit")
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )

    kits = list_all_kits()
    assert any(k.name == "compat-kit" for k in kits)


# ---------------------------------------------------------------------------
# REST layer endpoints (integration via TestClient)
# ---------------------------------------------------------------------------


def _make_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    layers: list[KitLayerConfig],
) -> "TestClient":
    """
    Build an auth-free TestClient with the given layers configured.

    Uses the same stripped-down FastAPI pattern as ``test_kit_admin.py``
    to isolate routing + status mapping without auth middleware.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.main import _register_exception_handlers
    from app.media_types import VENDOR_MEDIA_TYPE
    from app.routers import kits_admin, kits_layers

    mock_settings = type(
        "S",
        (),
        {
            "kits_root": None,
            "effective_layers": layers,
        },
    )()

    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: mock_settings,
    )
    # These tests cover layer routing + status mapping, not authorization
    # (see test_authz.py); act as an editor so the write-gate is satisfied.
    monkeypatch.setattr("app.authz.is_editor", lambda _sub: True)

    app = FastAPI()
    app.include_router(kits_layers.router)
    app.include_router(kits_admin.router)
    _register_exception_handlers(app)
    return TestClient(app, headers={"Accept": VENDOR_MEDIA_TYPE})


_VENDOR = "application/vnd.instructions+json; v=1"


@pytest.mark.parametrize("name", ["base", "overlay"])
def test_rest_list_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """GET /api/kits/layers returns all configured layers."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    client = _make_client(monkeypatch, tmp_path, layers)
    resp = client.get("/api/kits/layers", headers={"Accept": _VENDOR})
    assert resp.status_code == 200
    layer_names = [l["name"] for l in resp.json()]
    assert name in layer_names


def test_rest_list_kits_in_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/kits/layers/{id} lists kits present in that layer."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    _make_kit(base, "base-kit")
    _make_kit(overlay, "overlay-kit")

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    client = _make_client(monkeypatch, tmp_path, layers)
    resp = client.get("/api/kits/layers/base", headers={"Accept": _VENDOR})
    assert resp.status_code == 200
    names = [k["name"] for k in resp.json()]
    assert "base-kit" in names
    assert "overlay-kit" not in names


def test_rest_create_kit_in_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST /api/kits/layers/{id} creates a kit in the named layer."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    client = _make_client(monkeypatch, tmp_path, layers)

    payload = {
        "name": "new-rest-kit",
        "applicability": _APPLICABILITY,
        "summary": "New kit via REST",
        "sections": [
            {
                "file": "invariant.md",
                "title": "Core",
                "gloss": "Core",
                "always_load": True,
                "body": "# Core\n\nBody.",
            }
        ],
    }
    resp = client.post(
        "/api/kits/layers/overlay",
        json=payload,
        headers={"Accept": _VENDOR, "Content-Type": "application/json"},
    )
    assert resp.status_code == 201
    assert (overlay / "new-rest-kit").is_dir()
    assert not (base / "new-rest-kit").exists()


def test_rest_create_kit_readonly_layer_403(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST to a readonly layer returns 403."""
    base = tmp_path / "base"
    base.mkdir()

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
    ]
    client = _make_client(monkeypatch, tmp_path, layers)

    payload = {
        "name": "blocked-kit",
        "applicability": _APPLICABILITY,
        "summary": "Should be blocked",
        "sections": [
            {
                "file": "invariant.md",
                "title": "Core",
                "gloss": "Core",
                "always_load": True,
                "body": "# Core\n\nBody.",
            }
        ],
    }
    resp = client.post(
        "/api/kits/layers/base",
        json=payload,
        headers={"Accept": _VENDOR, "Content-Type": "application/json"},
    )
    assert resp.status_code == 403


def test_rest_delete_kit_from_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DELETE /api/kits/layers/{id}/{name} deletes from that layer only."""
    base = tmp_path / "base"
    overlay = tmp_path / "overlay"
    base.mkdir()
    overlay.mkdir()

    _make_kit(base, "to-delete")
    _make_kit(overlay, "to-delete")

    layers = [
        KitLayerConfig(name="base", path=base, readonly=True),
        KitLayerConfig(name="overlay", path=overlay, readonly=False),
    ]
    client = _make_client(monkeypatch, tmp_path, layers)
    resp = client.delete(
        "/api/kits/layers/overlay/to-delete",
        headers={"Accept": _VENDOR},
    )
    assert resp.status_code == 204
    assert not (overlay / "to-delete").exists()
    assert (base / "to-delete").is_dir()


def test_rest_unknown_layer_404(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GET /api/kits/layers/{unknown} returns 404."""
    layers = [
        KitLayerConfig(name="base", path=tmp_path, readonly=True)
    ]
    client = _make_client(monkeypatch, tmp_path, layers)
    resp = client.get(
        "/api/kits/layers/nonexistent",
        headers={"Accept": _VENDOR},
    )
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WebDAV layer resolution honors the same precedence
# ---------------------------------------------------------------------------


def test_webdav_resolves_from_layers_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_resolve_layers reads QM_KIT_LAYERS_FILE (highest precedence)."""
    from app.dav.webdav_app import _resolve_layers

    (tmp_path / "company").mkdir()
    (tmp_path / "team").mkdir()
    toml_file = tmp_path / "layers.toml"
    toml_file.write_text(
        "[[layer]]\n"
        'name = "company"\n'
        'path = "company"\n'
        "readonly = true\n\n"
        "[[layer]]\n"
        'name = "team"\n'
        'path = "team"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("QM_KIT_LAYERS_FILE", str(toml_file))
    monkeypatch.setenv("QM_KITS_ROOT", str(tmp_path / "ignored"))

    resolved = _resolve_layers()
    assert [(n, ro) for n, _p, ro in resolved] == [
        ("company", True),
        ("team", False),
    ]
    # Relative paths resolved against the TOML file's directory.
    assert resolved[0][1] == (tmp_path / "company").resolve()


def test_webdav_single_root_backward_compat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With only QM_KITS_ROOT, _resolve_layers yields one 'default' layer."""
    from app.dav.webdav_app import _resolve_layers

    monkeypatch.delenv("QM_KIT_LAYERS_FILE", raising=False)
    monkeypatch.setenv("QM_KITS_ROOT", str(tmp_path))

    resolved = _resolve_layers()
    assert resolved == [("default", tmp_path, False)]
