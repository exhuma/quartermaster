"""
Tests for versioned kit discovery and content access.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.kits import (
    WEIGHT_LANGUAGES,
    WEIGHT_REQUIRE_SATISFIED,
    KitApplicability,
    KitInfo,
    KitNotFoundError,
    KitSectionNotFoundError,
    KitVersionNotFoundError,
    ProjectTraits,
    _catalog_entries,
    _evaluate_candidate,
    _kit_version_paths,
    _load_kit_index,
    _parse_changelog,
    _parse_version_tuple,
    _validate_manifest,
    _version_key,
    compare_kit_versions,
    resolve_effective_version,
    explain_kit_v2,
    list_all_kits,
    list_available_traits_v2,
    list_catalog_v2,
    read_kit,
    read_kit_outline,
    select_kits_v2,
)


def _write_kit_version(
    base: Path,
    kit: str,
    ver: str,
    summary: str,
    sections: list[dict],
) -> None:
    """Create ``base/<kit>/<ver>/instructions/`` with index.toml + files.

    Each section dict has ``file``, ``title``, ``body`` and optional
    ``gloss`` / ``always_load``.
    """
    instr = base / kit / ver / "instructions"
    instr.mkdir(parents=True)
    lines = [f'summary = "{summary}"', ""]
    for s in sections:
        (instr / s["file"]).write_text(s["body"], encoding="utf-8")
        lines += [
            "[[sections]]",
            f'file = "{s["file"]}"',
            f'title = "{s["title"]}"',
            f'gloss = "{s.get("gloss", s["title"])}"',
            f'always_load = {"true" if s.get("always_load") else "false"}',
            "",
        ]
    (instr / "index.toml").write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def kit_root(tmp_path: Path) -> Path:
    """Create a temporary kits root with two versioned kits."""
    # kit-alpha  v1 and v2
    for ver in ("v1", "v2"):
        _write_kit_version(
            tmp_path,
            "kit-alpha",
            ver,
            summary=f"Alpha {ver} summary.",
            sections=[
                {
                    "file": "overview.md",
                    "title": "Overview",
                    "gloss": "What this kit is",
                    "body": f"# Agent instructions: kit-alpha {ver}\n",
                },
                {
                    "file": "invariant.md",
                    "title": "Architecture invariants",
                    "gloss": "Non-negotiables",
                    "always_load": True,
                    "body": (
                        f"## Architecture invariants\n\n"
                        f"Keep {ver} layered.\n"
                    ),
                },
                {
                    "file": "tooling.md",
                    "title": "Tooling",
                    "gloss": "Project setup",
                    "body": "## Tooling\n\nUse uv.\n",
                },
            ],
        )
    # kit-beta  v1 only
    _write_kit_version(
        tmp_path,
        "kit-beta",
        "v1",
        summary="Beta summary.",
        sections=[
            {
                "file": "overview.md",
                "title": "Overview",
                "body": "# Agent instructions: kit-beta\n",
            }
        ],
    )

    (tmp_path / "kit-alpha" / "applicability.json").write_text(
        json.dumps(
            {
                "kit_type": "module",
                "summary": "FastAPI backend guidance for Python services.",
                "domains": ["api-design", "backend"],
                "languages": ["python"],
                "frameworks": ["fastapi"],
                "contexts": ["backend"],
                "requires": {
                    "languages": ["python"],
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
                "optional_signals": ["rest-api", "async"],
                "related_kits": ["kit-beta"],
                "priority": 70,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "kit-beta" / "applicability.json").write_text(
        json.dumps(
            {
                "kit_type": "module",
                "summary": "Vue frontend guidance for TypeScript apps.",
                "domains": ["frontend", "ui"],
                "languages": ["typescript"],
                "frameworks": ["vue"],
                "contexts": ["frontend"],
                "requires": {
                    "languages": [],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
                "excludes": {
                    "languages": ["python"],
                    "frameworks": [],
                    "capabilities": [],
                    "contexts": [],
                },
                "optional_signals": ["spa", "components"],
                "related_kits": [],
                "priority": 40,
            }
        ),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def kit_with_changelog(tmp_path: Path) -> Path:
    """Create a kit root with a CHANGELOG.md for compare tests."""
    _write_kit_version(
        tmp_path,
        "my-kit",
        "v1",
        summary="My kit summary.",
        sections=[
            {
                "file": "overview.md",
                "title": "Overview",
                "body": "# Agent instructions: my-kit\n",
            }
        ],
    )
    changelog = tmp_path / "my-kit" / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog: my-kit\n\n"
        "## v2.0.0 — Major refactor\n\n"
        "### Breaking Changes\n\n"
        "- Replaced authentication flow with new OAuth2 scheme.\n\n"
        "## v1.2.0 — Feature additions\n\n"
        "- Added export endpoint.\n\n"
        "## v1.1.0 — Minor fixes\n\n"
        "- Fixed typo in README.\n\n"
        "## v1.0.0 — Initial release\n\n"
        "- Initial release of my-kit.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture()
def kit_root_with_broken_manifest(kit_root: Path) -> Path:
    """A kit root where one kit's applicability.json is malformed JSON."""
    (kit_root / "kit-beta" / "applicability.json").write_text(
        "{ not json",
        encoding="utf-8",
    )
    return kit_root


@pytest.fixture()
def kit_root_with_broken_index(kit_root: Path) -> Path:
    """A kit root where one kit's index.toml references a missing file."""
    index = kit_root / "kit-beta" / "v1" / "instructions" / "index.toml"
    index.write_text(
        'summary = "Beta summary."\n\n'
        "[[sections]]\n"
        'file = "overview.md"\n'
        'title = "Overview"\n'
        'gloss = "g"\n'
        "always_load = false\n\n"
        "[[sections]]\n"
        'file = "gone.md"\n'  # references a section file that does not exist
        'title = "Gone"\n'
        'gloss = "g"\n'
        "always_load = false\n",
        encoding="utf-8",
    )
    return kit_root


# ---------------------------------------------------------------------------
# _load_kit_index
# ---------------------------------------------------------------------------


def test_load_kit_index_parses_sections(kit_root: Path) -> None:
    index_path = kit_root / "kit-alpha" / "v1" / "instructions" / "index.toml"
    index = _load_kit_index(index_path, "kit-alpha")
    assert index.summary == "Alpha v1 summary."
    assert [s.id for s in index.sections] == [
        "overview",
        "invariant",
        "tooling",
    ]
    invariant = next(s for s in index.sections if s.id == "invariant")
    assert invariant.always_load is True
    assert invariant.title == "Architecture invariants"


def test_load_kit_index_rejects_malformed_toml(tmp_path: Path) -> None:
    bad = tmp_path / "index.toml"
    bad.write_text("summary = \nsections = [", encoding="utf-8")
    with pytest.raises(ValueError):
        _load_kit_index(bad, "broken")


def test_load_kit_index_rejects_missing_section_file(tmp_path: Path) -> None:
    instr = tmp_path / "instructions"
    instr.mkdir()
    (instr / "index.toml").write_text(
        'summary = "s"\n\n[[sections]]\nfile = "gone.md"\n'
        'title = "Gone"\ngloss = "g"\nalways_load = false\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        _load_kit_index(instr / "index.toml", "kit")


# ---------------------------------------------------------------------------
# _version_key
# ---------------------------------------------------------------------------


def test_version_key_numeric() -> None:
    assert _version_key("v3") == 3
    assert _version_key("v10") == 10


def test_version_key_invalid_returns_zero() -> None:
    assert _version_key("main") == 0
    assert _version_key("v") == 0


# ---------------------------------------------------------------------------
# _parse_version_tuple
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "version, expected",
    [
        ("v1", (1,)),
        ("v1.2", (1, 2)),
        ("v1.2.3", (1, 2, 3)),
        ("1.0.0", (1, 0, 0)),
    ],
)
def test_parse_version_tuple(
    version: str, expected: tuple[int, ...]
) -> None:
    assert _parse_version_tuple(version) == expected


# ---------------------------------------------------------------------------
# _kit_version_paths
# ---------------------------------------------------------------------------


def test_kit_version_paths_finds_versioned_kits(
    kit_root: Path,
) -> None:
    paths = _kit_version_paths(kit_root)
    assert set(paths.keys()) == {"kit-alpha", "kit-beta"}
    assert set(paths["kit-alpha"].keys()) == {"v1", "v2"}
    assert set(paths["kit-beta"].keys()) == {"v1"}


def test_kit_version_paths_versions_sorted(kit_root: Path) -> None:
    paths = _kit_version_paths(kit_root)
    assert list(paths["kit-alpha"].keys()) == ["v1", "v2"]


def test_kit_version_paths_ignores_non_version_dirs(
    tmp_path: Path,
) -> None:
    # A directory named "main" should be ignored.
    bad_dir = tmp_path / "kit-bad" / "main" / "instructions"
    bad_dir.mkdir(parents=True)
    (bad_dir / "index.toml").write_text('summary = "x"\n', encoding="utf-8")
    paths = _kit_version_paths(tmp_path)
    assert "kit-bad" not in paths


# ---------------------------------------------------------------------------
# list_all_kits (via patched settings)
# ---------------------------------------------------------------------------


def test_list_all_kits(kit_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    kits = list_all_kits()
    names = [k.name for k in kits]
    assert "kit-alpha" in names
    assert "kit-beta" in names


def test_list_all_kits_latest_version(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    alpha = next(k for k in list_all_kits() if k.name == "kit-alpha")
    assert alpha.latest_version == "v2"
    assert alpha.versions == ["v1", "v2"]


def test_list_all_kits_description_from_latest(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    alpha = next(k for k in list_all_kits() if k.name == "kit-alpha")
    assert alpha.description == "Alpha v2 summary."


def test_list_all_kits_flags_broken_index_without_crashing(
    kit_root_with_broken_index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A single malformed kit index must not abort the whole catalog: the good
    # kit still loads, and the bad one is returned flagged as broken.
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root_with_broken_index})(),
    )
    kits = list_all_kits()
    by_name = {k.name: k for k in kits}
    assert "kit-alpha" in by_name and "kit-beta" in by_name

    alpha = by_name["kit-alpha"]
    assert alpha.broken is False and alpha.error is None

    beta = by_name["kit-beta"]
    assert beta.broken is True
    assert beta.error and "gone" in beta.error
    # Path-derived metadata still populated for the broken kit.
    assert beta.versions == ["v1"]
    assert beta.latest_version == "v1"


def test_broken_kit_excluded_from_selection(
    kit_root_with_broken_index: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The broken kit must never be offered to the selector/resolver, but the
    # catalog scan itself must not raise.
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root_with_broken_index})(),
    )
    entries, warnings = _catalog_entries()
    entry_names = [info.name for info, _ in entries]
    assert "kit-alpha" in entry_names
    assert "kit-beta" not in entry_names
    assert any(w["kit"] == "kit-beta" for w in warnings)

    catalog = list_catalog_v2()
    assert all(c["name"] != "kit-beta" for c in catalog)


# ---------------------------------------------------------------------------
# read_kit (via patched settings)
# ---------------------------------------------------------------------------


def test_read_kit_latest_by_default(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    content = read_kit("kit-alpha")
    assert "v2" in content


def test_read_kit_specific_version(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    content = read_kit("kit-alpha", "v1")
    assert "v1" in content
    assert "v2" not in content


def test_read_kit_not_found(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    with pytest.raises(KitNotFoundError):
        read_kit("nonexistent")


def test_read_kit_version_not_found(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    with pytest.raises(KitVersionNotFoundError):
        read_kit("kit-alpha", "v99")


def test_read_kit_full_concatenates_sections(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    content = read_kit("kit-alpha", "v1")
    # All three sections appear, in document order.
    assert content.index("kit-alpha v1") < content.index(
        "Architecture invariants"
    ) < content.index("Tooling")


def test_read_kit_sections_subset_in_order(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    # Request out of order; result follows document order.
    content = read_kit("kit-alpha", "v1", sections=["tooling", "invariant"])
    assert "Tooling" in content
    assert "Architecture invariants" in content
    assert "Agent instructions" not in content  # overview excluded
    assert content.index("Architecture invariants") < content.index("Tooling")


def test_read_kit_unknown_section_raises(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    with pytest.raises(KitSectionNotFoundError) as exc:
        read_kit("kit-alpha", "v1", sections=["nope"])
    assert "nope" in exc.value.unknown
    assert "invariant" in exc.value.valid


# ---------------------------------------------------------------------------
# read_kit_outline
# ---------------------------------------------------------------------------


def test_read_kit_outline_lists_sections(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    outline = read_kit_outline("kit-alpha")
    assert outline["name"] == "kit-alpha"
    assert outline["version"] == "v2"
    assert outline["summary"] == "Alpha v2 summary."
    ids = [s["id"] for s in outline["sections"]]
    assert ids == ["overview", "invariant", "tooling"]
    invariant = next(s for s in outline["sections"] if s["id"] == "invariant")
    assert invariant["always_load"] is True
    assert invariant["bytes"] > 0
    assert "gloss" in invariant


def test_read_kit_outline_not_found(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    with pytest.raises(KitNotFoundError):
        read_kit_outline("nonexistent")


# ---------------------------------------------------------------------------
# _parse_changelog
# ---------------------------------------------------------------------------


def test_parse_changelog_sections() -> None:
    content = (
        "# Changelog\n\n"
        "## v2.0.0 — Big change\n\nAdded feature X.\n\n"
        "## v1.0.0 — Initial\n\nFirst release.\n"
    )
    sections = _parse_changelog(content)
    assert list(sections.keys()) == ["v2.0.0", "v1.0.0"]
    assert "feature X" in sections["v2.0.0"]
    assert "First release" in sections["v1.0.0"]


def test_parse_changelog_empty() -> None:
    assert _parse_changelog("") == {}


# ---------------------------------------------------------------------------
# compare_kit_versions (via patched settings)
# ---------------------------------------------------------------------------


def test_compare_kit_versions_range(
    kit_with_changelog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_with_changelog})(),
    )
    result = compare_kit_versions("my-kit", "v1.0.0", "v1.2.0")
    versions = [c["version"] for c in result["changes"]]
    assert "v1.1.0" in versions
    assert "v1.2.0" in versions
    assert "v1.0.0" not in versions  # exclusive lower bound
    assert "v2.0.0" not in versions  # above upper bound


def test_compare_kit_versions_user_facing_warning(
    kit_with_changelog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_with_changelog})(),
    )
    # v2.0.0 section mentions "authentication"
    result = compare_kit_versions("my-kit", "v1.2.0", "v2.0.0")
    assert result["user_facing_warning"] is True


def test_compare_kit_versions_no_user_facing_warning(
    kit_with_changelog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_with_changelog})(),
    )
    # v1.1.0 only mentions a README typo fix — not user-facing
    result = compare_kit_versions("my-kit", "v1.0.0", "v1.1.0")
    assert result["user_facing_warning"] is False


def test_compare_kit_versions_kit_not_found(
    kit_with_changelog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_with_changelog})(),
    )
    with pytest.raises(KitNotFoundError):
        compare_kit_versions("missing-kit", "v1.0.0", "v2.0.0")


def test_compare_kit_versions_no_changelog(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    with pytest.raises(FileNotFoundError):
        compare_kit_versions("kit-alpha", "v1", "v2")


def test_compare_kit_versions_oldest_first(
    kit_with_changelog: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_with_changelog})(),
    )
    result = compare_kit_versions("my-kit", "v1.0.0", "v2.0.0")
    versions = [c["version"] for c in result["changes"]]
    # Should be in ascending order
    tuples = [_parse_version_tuple(v) for v in versions]
    assert tuples == sorted(tuples)


# ---------------------------------------------------------------------------
# V2 discovery APIs
# ---------------------------------------------------------------------------


def test_list_catalog_v2_contains_compact_fields(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    result = list_catalog_v2()
    alpha = next(item for item in result if item["name"] == "kit-alpha")
    assert alpha["kit_type"] == "module"
    assert "summary" in alpha
    assert "requires" in alpha


def test_select_kits_v2_prefers_matching_kit(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    result = select_kits_v2(
        languages=["python"],
        frameworks=["fastapi"],
        capabilities=["rest-api"],
        contexts=["backend"],
    )
    names = [item["name"] for item in result["candidates"]]
    assert names[0] == "kit-alpha"
    assert "kit-beta" not in names


def test_select_kits_v2_recommends_broadening_for_sparse_traits(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    result = select_kits_v2(
        languages=["python"],
        frameworks=None,
        capabilities=None,
        contexts=None,
    )
    assert result["broadening_recommended"] is True


def test_explain_kit_v2_returns_constraints_and_reasons(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    result = explain_kit_v2(
        name="kit-alpha",
        languages=["python"],
        frameworks=["fastapi"],
    )
    assert result["name"] == "kit-alpha"
    assert result["ineligible"] is False
    assert "requires" in result
    assert any(reason.startswith("match:") for reason in result["reasons"])


def test_list_available_traits_v2_aggregates_vocab(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    traits = list_available_traits_v2()
    assert traits["trait_keys"] == [
        "languages",
        "frameworks",
        "capabilities",
        "contexts",
    ]
    assert "python" in traits["languages"]
    assert "fastapi" in traits["frameworks"]
    assert "rest-api" in traits["capabilities"]
    assert "backend" in traits["contexts"]
    assert "api-design" in traits["domains"]
    assert "async" in traits["optional_signals"]


# ---------------------------------------------------------------------------
# Catalog robustness (partial load)
# ---------------------------------------------------------------------------


def test_catalog_entries_collects_warnings(
    kit_root_with_broken_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root_with_broken_manifest})(),
    )
    entries, warnings = _catalog_entries()
    names = [info.name for info, _ in entries]
    assert names == ["kit-alpha"]
    assert len(warnings) == 1
    assert warnings[0]["kit"] == "kit-beta"
    assert "error" in warnings[0]


def test_catalog_entries_strict_raises(
    kit_root_with_broken_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root_with_broken_manifest})(),
    )
    with pytest.raises(ValueError):
        _catalog_entries(strict=True)


_BASE_MANIFEST = {
    "kit_type": "module",
    "summary": "Some kit.",
    "domains": ["governance"],
    "languages": [],
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
    "priority": 10,
}


def test_always_apply_parses_as_optional_bool() -> None:
    # Present bool.
    assert (
        _validate_manifest({**_BASE_MANIFEST, "always_apply": True}, "k")
    ).always_apply is True
    # Absent -> defaults False (legacy manifests are unaffected).
    assert _validate_manifest(dict(_BASE_MANIFEST), "k").always_apply is False
    # Non-bool -> rejected.
    with pytest.raises(ValueError):
        _validate_manifest({**_BASE_MANIFEST, "always_apply": "yes"}, "k")


def _write_policy_kit(base: Path, name: str, manifest_extra: dict) -> None:
    _write_kit_version(
        base,
        name,
        "v1",
        summary=f"{name} summary.",
        sections=[
            {
                "file": "invariant.md",
                "title": "Policy",
                "gloss": "Baseline policy",
                "always_load": True,
                "body": "## Policy\n\nRules.\n",
            }
        ],
    )
    (base / name / "applicability.json").write_text(
        json.dumps({**_BASE_MANIFEST, **manifest_extra}), encoding="utf-8"
    )


def test_select_kits_v2_injects_global_policy_kit(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A global policy kit (always_apply, no requires) that matches nothing is
    # still injected, below threshold, flagged policy=True.
    _write_policy_kit(kit_root, "kit-policy", {"always_apply": True})
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    result = select_kits_v2(
        languages=["python"], frameworks=["fastapi"], contexts=["backend"]
    )
    by_name = {c["name"]: c for c in result["candidates"]}
    assert "kit-policy" in by_name
    assert by_name["kit-policy"]["policy"] is True


def test_select_kits_v2_pending_policy_kit_emits_need_trait(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A project-type policy kit requiring a language not provided is injected
    # and surfaces need-trait + needs so clarification can pick it up.
    _write_policy_kit(
        kit_root,
        "kit-py-policy",
        {
            "always_apply": True,
            "requires": {
                "languages": ["python"],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
        },
    )
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root})(),
    )
    result = select_kits_v2(frameworks=["fastapi"])
    by_name = {c["name"]: c for c in result["candidates"]}
    assert "kit-py-policy" in by_name
    assert "need-trait:languages" in by_name["kit-py-policy"]["reasons"]
    assert by_name["kit-py-policy"]["needs"] == {"languages": ["python"]}


def test_select_kits_v2_policy_disabled_skips_injection(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_policy_kit(kit_root, "kit-policy", {"always_apply": True})
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type(
            "S", (), {"kits_root": kit_root, "policy_enabled": False}
        )(),
    )
    result = select_kits_v2(
        languages=["python"], frameworks=["fastapi"], contexts=["backend"]
    )
    names = [c["name"] for c in result["candidates"]]
    assert "kit-policy" not in names


def test_select_kits_v2_skips_broken_manifest(
    kit_root_with_broken_manifest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": kit_root_with_broken_manifest})(),
    )
    result = select_kits_v2(
        languages=["python"],
        frameworks=["fastapi"],
        capabilities=["rest-api"],
        contexts=["backend"],
    )
    names = [item["name"] for item in result["candidates"]]
    assert "kit-alpha" in names
    assert any(w["kit"] == "kit-beta" for w in result["warnings"])


# ---------------------------------------------------------------------------
# Selector scoring model
# ---------------------------------------------------------------------------


def test_evaluate_candidate_scoring_constants() -> None:
    """A language-only match adds the language weight plus the satisfied
    `requires` weight on top of the kit's base priority."""
    applicability = KitApplicability(
        kit_type="module",
        summary="x",
        domains=[],
        languages=["python"],
        frameworks=[],
        contexts=[],
        requires={
            "languages": ["python"],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        excludes={
            "languages": [],
            "frameworks": [],
            "capabilities": [],
            "contexts": [],
        },
        optional_signals=[],
        related_kits=[],
        priority=70,
    )
    info = KitInfo(
        name="kit-x",
        description="x",
        versions=["v1"],
        latest_version="v1",
    )
    traits = ProjectTraits(
        languages=["python"],
        frameworks=[],
        capabilities=[],
        contexts=[],
    )
    result = _evaluate_candidate(info, applicability, traits)
    assert result["score"] == 70 + WEIGHT_LANGUAGES + WEIGHT_REQUIRE_SATISFIED
    assert result["ineligible"] is False


# ---------------------------------------------------------------------------
# Changelog user-facing keyword detection
# ---------------------------------------------------------------------------


def test_compare_kit_versions_no_false_positive_substring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Words that merely contain a keyword as a substring must not trip
    the user-facing warning (the old `user.facing` wildcard did)."""
    ai_dir = tmp_path / "my-kit" / "v1" / ".ai"
    ai_dir.mkdir(parents=True)
    (ai_dir / "instructions.md").write_text(
        "# Agent instructions: my-kit\n\nDescription.", encoding="utf-8"
    )
    (tmp_path / "my-kit" / "CHANGELOG.md").write_text(
        "# Changelog: my-kit\n\n"
        "## v1.1.0 — Docs\n\n"
        "- Improved therapist scheduling wording (userXfacing).\n\n"
        "## v1.0.0 — Initial\n\n- First release.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )
    result = compare_kit_versions("my-kit", "v1.0.0", "v1.1.0")
    assert result["user_facing_warning"] is False


def test_compare_kit_versions_routes_is_user_facing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_dir = tmp_path / "my-kit" / "v1" / ".ai"
    ai_dir.mkdir(parents=True)
    (ai_dir / "instructions.md").write_text(
        "# Agent instructions: my-kit\n\nDescription.", encoding="utf-8"
    )
    (tmp_path / "my-kit" / "CHANGELOG.md").write_text(
        "# Changelog: my-kit\n\n"
        "## v1.1.0 — Routing\n\n- Renamed several API routes.\n\n"
        "## v1.0.0 — Initial\n\n- First release.\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )
    result = compare_kit_versions("my-kit", "v1.0.0", "v1.1.0")
    assert result["user_facing_warning"] is True


# ---------------------------------------------------------------------------
# Real catalog integrity (the shipped kits/ directory)
# ---------------------------------------------------------------------------


# Resolve the catalog from KITS_ROOT (the production knob), falling back to
# this repo's bundled kits/ for a source checkout. These integration tests
# require the catalog to be present; the released core ships without it, so
# they skip cleanly when no catalog is mounted.
_REAL_KITS_ROOT = Path(
    os.environ.get(
        "QM_KITS_ROOT", str(Path(__file__).resolve().parents[2] / "kits")
    )
)

# The catalog is "present" only if it actually holds kits — an existing but
# empty directory (e.g. the throwaway KITS_ROOT used in CI) does not count,
# so these integration tests skip cleanly when no real catalog is mounted.
_REAL_CATALOG_PRESENT = _REAL_KITS_ROOT.is_dir() and any(
    _REAL_KITS_ROOT.glob("*/applicability.json")
)

requires_real_catalog = pytest.mark.skipif(
    not _REAL_CATALOG_PRESENT,
    reason=f"kit catalog not present at {_REAL_KITS_ROOT}",
)


@pytest.fixture()
def real_kits(monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": _REAL_KITS_ROOT})(),
    )
    return _REAL_KITS_ROOT


@requires_real_catalog
def test_real_catalog_loads(real_kits: Path) -> None:
    kits = list_all_kits()
    assert len(kits) >= 26
    # Every kit's index loads and yields a non-empty summary + sections.
    for kit in kits:
        outline = read_kit_outline(kit.name)
        assert outline["summary"]
        assert outline["sections"]
        # Full read concatenates without error and is non-trivial.
        assert len(read_kit(kit.name)) > 0


@requires_real_catalog
def test_real_catalog_v2_loads_without_warnings(real_kits: Path) -> None:
    catalog = list_catalog_v2()
    assert len(catalog) >= 26


@requires_real_catalog
def test_real_kit_sections_are_retrievable(real_kits: Path) -> None:
    outline = read_kit_outline("module-database-postgresql")
    ids = [s["id"] for s in outline["sections"]]
    assert "architecture-invariants" in ids
    assert any(s["always_load"] for s in outline["sections"])
    subset = read_kit(
        "module-database-postgresql", sections=["architecture-invariants"]
    )
    full = read_kit("module-database-postgresql")
    assert "Architecture invariants" in subset
    assert len(subset) < len(full)


# ---------------------------------------------------------------------------
# resolve_effective_version + version advisories
# ---------------------------------------------------------------------------


def _use_root(monkeypatch: pytest.MonkeyPatch, root: Path) -> None:
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": root})(),
    )


def test_effective_version_single_version_no_advisory(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    served, advisory = resolve_effective_version("kit-beta")
    assert served == "v1"
    assert advisory is None


def test_effective_version_unpinned_multi_serves_earliest_with_advisory(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    served, advisory = resolve_effective_version("kit-alpha")
    assert served == "v1"
    assert advisory is not None
    assert advisory["reason"] == "unpinned-multi-version"
    assert advisory["served_version"] == "v1"
    assert advisory["latest_version"] == "v2"
    assert advisory["available_versions"] == ["v1", "v2"]
    assert advisory["pin_file_hint"]["key"] == "kit-alpha"
    # kit-alpha has no CHANGELOG in the fixture: degrade to an empty list.
    assert advisory["breaking_changes"] == []
    assert advisory["user_facing_warning"] is False


def test_effective_version_valid_pin_no_advisory(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    served, advisory = resolve_effective_version("kit-alpha", pin="v2")
    assert served == "v2"
    assert advisory is None


def test_effective_version_invalid_pin_falls_back_with_advisory(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    served, advisory = resolve_effective_version("kit-alpha", pin="v9")
    assert served == "v1"
    assert advisory is not None
    assert advisory["reason"] == "pin-invalid"


def test_effective_version_explicit_version_wins(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    served, advisory = resolve_effective_version("kit-alpha", version="v1")
    assert served == "v1"
    assert advisory is None


def test_effective_version_explicit_unknown_version_raises(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    with pytest.raises(KitVersionNotFoundError):
        resolve_effective_version("kit-alpha", version="v9")


def test_effective_version_unknown_kit_raises(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _use_root(monkeypatch, kit_root)
    with pytest.raises(KitNotFoundError):
        resolve_effective_version("does-not-exist")


def test_advisory_populates_breaking_changes_from_changelog(
    kit_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Add a CHANGELOG so the advisory carries the v2 breaking summary, and only
    # the entries whose *major* is above the served major (excludes v1.x).
    (kit_root / "kit-alpha" / "CHANGELOG.md").write_text(
        "# Changelog: kit-alpha\n\n"
        "## v2.0.0 — Major refactor\n\n"
        "- Replaced the authentication flow (breaking).\n\n"
        "## v1.1.0 — Minor\n\n"
        "- Fixed a typo.\n\n"
        "## v1.0.0 — Initial\n\n"
        "- Initial release.\n",
        encoding="utf-8",
    )
    _use_root(monkeypatch, kit_root)
    _served, advisory = resolve_effective_version("kit-alpha")
    assert advisory is not None
    versions = [c["version"] for c in advisory["breaking_changes"]]
    assert versions == ["v2.0.0"]
    assert advisory["user_facing_warning"] is True
