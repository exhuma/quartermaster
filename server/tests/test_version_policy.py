"""Tests for operator version policy: parsing and advisory enforcement."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import load_version_policy_from_toml
from app.kits import resolve_effective_version


def _write_kit_version(base: Path, kit: str, ver: str) -> None:
    instr = base / kit / ver / "instructions"
    instr.mkdir(parents=True)
    (instr / "invariant.md").write_text("## Inv\nbody\n", encoding="utf-8")
    (instr / "index.toml").write_text(
        'summary = "s"\n\n[[sections]]\n'
        'file = "invariant.md"\ntitle = "Inv"\ngloss = "g"\n'
        "always_load = true\n",
        encoding="utf-8",
    )


@pytest.fixture()
def multi_kit_root(tmp_path: Path) -> Path:
    for ver in ("v1", "v2", "v3"):
        _write_kit_version(tmp_path, "kit-alpha", ver)
    return tmp_path


def test_load_version_policy_parses_kits_table(tmp_path: Path) -> None:
    policy_file = tmp_path / "policy.toml"
    policy_file.write_text(
        "[kits.module-auth-oidc]\n"
        'min_version = "v2"\n'
        'deprecated = ["v1"]\n',
        encoding="utf-8",
    )
    policy = load_version_policy_from_toml(policy_file)
    assert policy["module-auth-oidc"]["min_version"] == "v2"
    assert policy["module-auth-oidc"]["deprecated"] == ["v1"]


def test_load_version_policy_missing_file_is_empty(tmp_path: Path) -> None:
    assert load_version_policy_from_toml(tmp_path / "nope.toml") == {}


def test_policy_min_version_raises_the_conservative_floor(
    multi_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Settings:
        kits_root = multi_kit_root
        conservative_default_enabled = True

        def version_policy(self) -> dict:
            return {"kit-alpha": {"min_version": "v2", "deprecated": ["v1"]}}

    monkeypatch.setattr("app.kits.get_settings", lambda: _Settings())
    served, advisory = resolve_effective_version("kit-alpha")
    # Conservative pick would be v1, but the policy floor lifts it to v2.
    assert served == "v2"
    assert advisory is not None
    assert advisory["reason"] == "policy-min-version"
    assert advisory["policy"]["min_version"] == "v2"


def test_conservative_default_disabled_serves_latest(
    multi_kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Settings:
        kits_root = multi_kit_root
        conservative_default_enabled = False

        def version_policy(self) -> dict:
            return {}

    monkeypatch.setattr("app.kits.get_settings", lambda: _Settings())
    served, advisory = resolve_effective_version("kit-alpha")
    assert served == "v3"
    assert advisory is None
