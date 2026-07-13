"""Evaluation corpus for kit resolution.

Two sources, combined:

* **catalog-derived** — one probe per real kit, generated from its manifest.
  The kit's own ``requires`` are the traits that *should* be inferred; its
  ``excludes`` are the traits that must *not* be inferred (inferring one would
  silently drop the kit). Comprehensive per-kit coverage with no hand-labeling,
  so it works for any catalog an instance serves.
* **curated** — a bundled ``cases/curated.yaml`` of natural, mostly-monolingual
  tasks that pin the cross-language contamination the embedding engine is prone
  to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TRAIT_CATEGORIES = ("languages", "frameworks", "capabilities", "contexts")

# The literal placeholder kit shipped in the catalog; carries no real traits.
_SKIP_KITS = {"test"}

CURATED_PATH = Path(__file__).parent / "cases" / "curated.yaml"


@dataclass(frozen=True)
class Case:
    """One probe: a task plus what its resolution should (not) contain."""

    id: str
    task: str
    source: str  # "catalog" | "curated"
    # category -> traits that SHOULD appear in inferred_traits
    expect_include: dict[str, list[str]] = field(default_factory=dict)
    # category -> traits that must NOT appear in inferred_traits
    expect_forbid: dict[str, list[str]] = field(default_factory=dict)
    kits_include: list[str] = field(default_factory=list)
    kits_forbid: list[str] = field(default_factory=list)

    def to_meta(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task": self.task,
            "source": self.source,
            "expect": {
                "include": self.expect_include,
                "forbid": self.expect_forbid,
                "kits_include": self.kits_include,
                "kits_forbid": self.kits_forbid,
            },
        }


def _clean_categories(raw: dict[str, Any] | None) -> dict[str, list[str]]:
    """Keep only the four known trait categories with non-empty value lists."""
    out: dict[str, list[str]] = {}
    for cat in TRAIT_CATEGORIES:
        vals = (raw or {}).get(cat) or []
        if vals:
            out[cat] = list(vals)
    return out


def _catalog_task_text(kit: dict[str, Any]) -> str:
    """Build a natural-ish task prompt from a kit's discovery metadata."""
    summary = str(kit.get("summary", "")).strip().rstrip(".")
    signals = [str(s) for s in (kit.get("top_signals") or [])]
    text = f"I'm working on a project that needs {summary.lower()}."
    if signals:
        text += f" Key concerns include {', '.join(signals)}."
    return text


def derive_from_catalog(catalog: list[dict[str, Any]]) -> list[Case]:
    """One probe per real kit, expectations taken from its manifest."""
    cases: list[Case] = []
    for kit in catalog:
        name = str(kit.get("name", "")).strip()
        if not name or name in _SKIP_KITS:
            continue
        requires = _clean_categories(kit.get("requires"))
        excludes = _clean_categories(kit.get("excludes"))
        cases.append(
            Case(
                id=f"catalog::{name}",
                task=_catalog_task_text(kit),
                source="catalog",
                expect_include=requires,
                expect_forbid=excludes,
                kits_include=[name],
            )
        )
    return cases


def _normalize_curated(raw: dict[str, Any], index: int) -> Case:
    cid = str(raw.get("id") or f"curated-{index}")
    task = raw.get("task")
    if not task:
        raise ValueError(f"curated case {cid!r} has no 'task'")
    expect = raw.get("expect") or {}
    return Case(
        id=f"curated::{cid}",
        task=str(task),
        source="curated",
        expect_include=_clean_categories(expect.get("include")),
        expect_forbid=_clean_categories(expect.get("forbid")),
        kits_include=list(
            raw.get("kits_include") or expect.get("kits_include") or []
        ),
        kits_forbid=list(
            raw.get("kits_forbid") or expect.get("kits_forbid") or []
        ),
    )


def load_curated(path: Path = CURATED_PATH) -> list[Case]:
    """Parse the curated language-purity suite from YAML."""
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    raw_cases = doc.get("cases") or []
    return [_normalize_curated(rc, i) for i, rc in enumerate(raw_cases)]


def build_cases(
    which: str,
    catalog: list[dict[str, Any]],
    curated_path: Path = CURATED_PATH,
) -> list[Case]:
    """Assemble the requested case set (``catalog`` | ``curated`` | ``all``)."""
    if which not in ("catalog", "curated", "all"):
        raise ValueError(f"unknown case set {which!r}")
    cases: list[Case] = []
    if which in ("curated", "all"):
        cases.extend(load_curated(curated_path))
    if which in ("catalog", "all"):
        cases.extend(derive_from_catalog(catalog))
    return cases
