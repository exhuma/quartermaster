"""Evaluation corpus for kit resolution — domain-agnostic.

The active kit root *is* the catalog, so the corpus adapts to whatever kits an
instance serves (software, baking, legal — anything). Two sources:

* **catalog-derived** — one probe per kit, generated from its manifest. The
  kit's own ``requires`` are the traits that *should* be inferred; its
  ``excludes`` are the traits that must *not* be inferred (inferring one would
  silently drop the kit). Comprehensive per-kit coverage with no hand-labeling.
* **authored** — an OPTIONAL ``eval-cases.yaml`` at the kit-catalog root,
  written by whoever owns the domain. Natural-language tasks with expected /
  forbidden traits and kits, in that domain's own vocabulary. Nothing
  domain-specific ships with the server; the author supplies it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

TRAIT_CATEGORIES = ("languages", "frameworks", "capabilities", "contexts")

# The literal placeholder kit shipped in some catalogs; carries no real traits.
_SKIP_KITS = {"test"}

# Conventional author-supplied cases file, discovered at the kit-catalog root.
# Kit discovery only scans ``*/applicability.json`` directories, so a plain
# file here never clashes with a kit.
AUTHOR_CASES_FILENAME = "eval-cases.yaml"

CASE_SETS = ("catalog", "authored", "all")


@dataclass(frozen=True)
class Case:
    """One probe: a task plus what its resolution should (not) contain."""

    id: str
    task: str
    source: str  # "catalog" | "authored"
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


def _normalize_authored(raw: dict[str, Any], index: int) -> Case:
    cid = str(raw.get("id") or f"case-{index}")
    task = raw.get("task")
    if not task:
        raise ValueError(f"authored case {cid!r} has no 'task'")
    expect = raw.get("expect") or {}
    return Case(
        id=f"authored::{cid}",
        task=str(task),
        source="authored",
        expect_include=_clean_categories(expect.get("include")),
        expect_forbid=_clean_categories(expect.get("forbid")),
        kits_include=list(
            raw.get("kits_include") or expect.get("kits_include") or []
        ),
        kits_forbid=list(
            raw.get("kits_forbid") or expect.get("kits_forbid") or []
        ),
    )


def load_author_cases(kits_root: Path | str | None) -> list[Case]:
    """Load the optional author-supplied ``eval-cases.yaml`` from the root.

    Returns ``[]`` when the root is unset or the file is absent — authored
    cases are optional.
    """
    if not kits_root:
        return []
    path = Path(kits_root) / AUTHOR_CASES_FILENAME
    if not path.exists():
        return []
    doc = yaml.safe_load(path.read_text()) or {}
    raw_cases = doc.get("cases") or []
    return [_normalize_authored(rc, i) for i, rc in enumerate(raw_cases)]


def build_cases(
    which: str,
    catalog: list[dict[str, Any]],
    kits_root: Path | str | None,
) -> list[Case]:
    """Assemble the requested set (``catalog`` | ``authored`` | ``all``)."""
    if which not in CASE_SETS:
        raise ValueError(
            f"unknown case set {which!r}; expected one of {CASE_SETS}"
        )
    cases: list[Case] = []
    if which in ("authored", "all"):
        cases.extend(load_author_cases(kits_root))
    if which in ("catalog", "all"):
        cases.extend(derive_from_catalog(catalog))
    return cases
