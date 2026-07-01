"""Owner-only visibility for private kits, across every enumeration path.

The core guarantees:

- A private kit is visible to its owner across list / catalog / select /
  read, and invisible (404) to any other caller and to the public path.
- The shared public catalog fingerprint (which keys the on-disk embedding
  cache) never changes when a private kit is added — no cache poisoning.
- On a name collision, the private kit shadows the public one FOR THE OWNER
  ONLY; everyone else still sees the public kit.
- The identity contextvar makes the default (argument-free) calls owner-aware,
  which is how MCP tools inherit private visibility.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import kits as kits_mod
from app.identity import reset_identity, set_identity
from app.private_kits import private_root_for


def _write_kit(base: Path, kit: str, summary: str, *, ver: str = "v1") -> None:
    """Create a minimal valid kit (index.toml + section + manifest)."""
    instr = base / kit / ver / "instructions"
    instr.mkdir(parents=True)
    (instr / "invariant.md").write_text(f"# {kit}\n\n{summary}\n", encoding="utf-8")
    (instr / "index.toml").write_text(
        "\n".join(
            [
                f'summary = "{summary}"',
                "",
                "[[sections]]",
                'file = "invariant.md"',
                'title = "Invariants"',
                'gloss = "Core rules"',
                "always_load = true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (base / kit / "applicability.json").write_text(
        json.dumps(
            {
                "kit_type": "module",
                "summary": summary,
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
        ),
        encoding="utf-8",
    )
    (base / kit / "CHANGELOG.md").write_text("## v1\n\nInitial.\n", encoding="utf-8")


@pytest.fixture()
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Public catalog + a private kit owned by 'alice'."""
    public = tmp_path / "kits"
    private = tmp_path / "private"
    _write_kit(public, "public-kit", "A public kit.")

    settings = SimpleNamespace(kits_root=public, private_kits_root=private)
    monkeypatch.setattr("app.kits.get_settings", lambda: settings)
    monkeypatch.setattr("app.private_kits.get_settings", lambda: settings)

    # Author a private kit for alice directly on disk under her hashed root.
    alice_root = private_root_for("alice-sub")
    _write_kit(alice_root, "alice-secret", "Alice's private kit.")
    return SimpleNamespace(public=public, private=private, alice="alice-sub")


def _names(kits) -> set[str]:
    return {k.name for k in kits}


def test_owner_sees_private_kit(catalog) -> None:
    names = _names(kits_mod.list_all_kits(subject=catalog.alice))
    assert names == {"public-kit", "alice-secret"}


def test_other_user_cannot_see_private_kit(catalog) -> None:
    assert _names(kits_mod.list_all_kits(subject="bob-sub")) == {"public-kit"}


def test_public_path_excludes_private_kit(catalog) -> None:
    assert _names(kits_mod.list_all_kits(subject=None)) == {"public-kit"}


def test_catalog_entries_owner_aware(catalog) -> None:
    owner, _ = kits_mod._catalog_entries(subject=catalog.alice)
    assert "alice-secret" in {info.name for info, _ in owner}
    public, _ = kits_mod._catalog_entries(subject=None)
    assert "alice-secret" not in {info.name for info, _ in public}


def test_owner_can_read_private_kit(catalog) -> None:
    content = kits_mod.read_kit("alice-secret", subject=catalog.alice)
    assert "Alice's private kit." in content


def test_other_user_read_private_kit_is_404(catalog) -> None:
    with pytest.raises(kits_mod.KitNotFoundError):
        kits_mod.read_kit("alice-secret", subject="bob-sub")
    with pytest.raises(kits_mod.KitNotFoundError):
        kits_mod.read_kit("alice-secret", subject=None)


def test_list_private_kits_helper(catalog) -> None:
    private = kits_mod.list_private_kits(catalog.alice)
    assert _names(private) == {"alice-secret"}
    assert kits_mod.list_private_kits("bob-sub") == []


def test_fingerprint_unchanged_by_private_kit(catalog) -> None:
    """The shared (public-only) fingerprint must ignore private kits."""
    from app.traits import catalog_fingerprint

    baseline = catalog_fingerprint()
    # Add another private kit for alice; the public fingerprint must not move.
    _write_kit(private_root_for(catalog.alice), "alice-extra", "More private.")
    assert catalog_fingerprint() == baseline
    # Even with alice bound in the identity context, fingerprint stays public.
    tokens = set_identity(catalog.alice, "Alice")
    try:
        assert catalog_fingerprint() == baseline
    finally:
        reset_identity(tokens)


def test_private_shadows_public_for_owner_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A private kit named like a public one shadows it only for the owner."""
    public = tmp_path / "kits"
    private = tmp_path / "private"
    _write_kit(public, "shared-name", "PUBLIC version.")
    settings = SimpleNamespace(kits_root=public, private_kits_root=private)
    monkeypatch.setattr("app.kits.get_settings", lambda: settings)
    monkeypatch.setattr("app.private_kits.get_settings", lambda: settings)
    _write_kit(private_root_for("alice-sub"), "shared-name", "PRIVATE version.")

    assert "PRIVATE version." in kits_mod.read_kit(
        "shared-name", subject="alice-sub"
    )
    assert "PUBLIC version." in kits_mod.read_kit("shared-name", subject="bob-sub")
    assert "PUBLIC version." in kits_mod.read_kit("shared-name", subject=None)


def test_contextvar_makes_default_calls_owner_aware(catalog) -> None:
    """MCP tools rely on the contextvar: no subject arg → owner-aware."""
    # No identity bound → public only.
    assert _names(kits_mod.list_all_kits()) == {"public-kit"}
    tokens = set_identity(catalog.alice, "Alice")
    try:
        assert "alice-secret" in _names(kits_mod.list_all_kits())
        assert "Alice's private kit." in kits_mod.read_kit("alice-secret")
    finally:
        reset_identity(tokens)
    # Cleared again after the request.
    assert _names(kits_mod.list_all_kits()) == {"public-kit"}
