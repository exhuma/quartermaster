"""Scoring and analysis over kit-resolution records. Pure, no I/O.

A *record* is one resolution outcome:

    {
      "id", "source", "engine",
      "inferred_traits": {languages, frameworks, capabilities, contexts},
      "kits": [{"name", "score"}, ...],     # kits that survived selection
      "expect": {include, forbid, kits_include, kits_forbid},
    }

``build_report`` turns a list of records + the catalog manifests into a
structured report: per-case verdicts, catalog-wide false-exclusions, language
contamination, and engine/determinism sanity.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .corpus import TRAIT_CATEGORIES

# Finding kinds that make a case "fail".
FAILING_KINDS = {
    "contamination",
    "missing-kit",
    "forbidden-kit",
    "engine-drift",
}


def _excludes_by_kit(
    catalog: list[dict[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    out: dict[str, dict[str, list[str]]] = {}
    for kit in catalog:
        name = kit.get("name")
        excludes = kit.get("excludes") or {}
        clean = {
            c: list(excludes.get(c) or [])
            for c in TRAIT_CATEGORIES
            if excludes.get(c)
        }
        if name and clean:
            out[name] = clean
    return out


def _inferred_sets(rec: dict[str, Any]) -> dict[str, set[str]]:
    inferred = rec.get("inferred_traits") or {}
    return {c: set(inferred.get(c) or []) for c in TRAIT_CATEGORIES}


def _kit_names(rec: dict[str, Any]) -> set[str]:
    return {k.get("name") for k in (rec.get("kits") or [])}


def verdict_for(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list of findings (empty == PASS) for one record."""
    findings: list[dict[str, Any]] = []
    inferred = _inferred_sets(rec)
    kits = _kit_names(rec)
    expect = rec.get("expect") or {}

    for cat, forbidden in (expect.get("forbid") or {}).items():
        leaked = sorted(set(forbidden) & inferred.get(cat, set()))
        if leaked:
            findings.append(
                {"kind": "contamination", "category": cat, "traits": leaked}
            )
    for cat, required in (expect.get("include") or {}).items():
        missing = sorted(set(required) - inferred.get(cat, set()))
        if missing:
            findings.append(
                {"kind": "recall-miss", "category": cat, "traits": missing}
            )
    for kit in expect.get("kits_include") or []:
        if kit not in kits:
            findings.append({"kind": "missing-kit", "kit": kit})
    for kit in expect.get("kits_forbid") or []:
        if kit in kits:
            findings.append({"kind": "forbidden-kit", "kit": kit})
    if rec.get("engine") != "embedding":
        findings.append({"kind": "engine-drift", "engine": rec.get("engine")})
    return findings


def false_exclusions(
    rec: dict[str, Any], excludes_by_kit: dict[str, dict[str, list[str]]]
) -> list[dict[str, Any]]:
    """Kits knocked out of a case by an inferred trait hitting excludes."""
    inferred = _inferred_sets(rec)
    forbid = rec.get("expect", {}).get("forbid") or {}
    out = []
    for kit, excludes in excludes_by_kit.items():
        offending: list[tuple[str, str]] = []
        confirmed = False
        for cat, values in excludes.items():
            hit = inferred.get(cat, set()) & set(values)
            for trait in sorted(hit):
                offending.append((cat, trait))
                # "confirmed spurious" == trait was labelled must-not-infer.
                if trait in set(forbid.get(cat) or []):
                    confirmed = True
        if offending:
            out.append(
                {
                    "kit": kit,
                    "offending": offending,
                    "confirmed_spurious": confirmed,
                }
            )
    return out


def build_report(
    records: list[dict[str, Any]], catalog: list[dict[str, Any]]
) -> dict[str, Any]:
    """Turn resolution records + catalog manifests into a scored report."""
    excludes_by_kit = _excludes_by_kit(catalog)

    # Group by case id; first repeat drives verdicts, all check determinism.
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in records:
        by_id[str(rec.get("id"))].append(rec)

    cases: list[dict[str, Any]] = []
    exclusion_tally: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "confirmed": 0, "by_trait": defaultdict(int)}
    )
    contamination: dict[str, dict[str, int]] = defaultdict(
        lambda: {"forbidden": 0, "leaked": 0}
    )
    engine_drift: list[str] = []
    nondeterministic: list[str] = []

    for cid, recs in by_id.items():
        primary = recs[0]
        findings = verdict_for(primary)
        fexcl = false_exclusions(primary, excludes_by_kit)
        for fe in fexcl:
            tally = exclusion_tally[fe["kit"]]
            tally["count"] += 1
            if fe["confirmed_spurious"]:
                tally["confirmed"] += 1
            for _cat, trait in fe["offending"]:
                tally["by_trait"][trait] += 1

        # language contamination accounting
        forbid_langs = set(
            (primary.get("expect", {}).get("forbid") or {}).get("languages")
            or []
        )
        inferred_langs = set(
            (primary.get("inferred_traits") or {}).get("languages") or []
        )
        for lang in forbid_langs:
            contamination[lang]["forbidden"] += 1
            if lang in inferred_langs:
                contamination[lang]["leaked"] += 1

        if primary.get("engine") != "embedding":
            engine_drift.append(cid)

        # determinism: identical inferred_traits across repeats?
        if len(recs) > 1:
            sigs = {
                json.dumps(r.get("inferred_traits"), sort_keys=True)
                for r in recs
            }
            if len(sigs) > 1:
                nondeterministic.append(cid)

        cases.append(
            {
                "id": cid,
                "source": primary.get("source"),
                "engine": primary.get("engine"),
                "task": primary.get("task"),
                "inferred_languages": sorted(inferred_langs),
                "findings": findings,
                "false_exclusions": fexcl,
                "passed": not any(f["kind"] in FAILING_KINDS for f in findings),
            }
        )

    failing = [c for c in cases if not c["passed"]]
    return {
        "totals": {
            "cases": len(cases),
            "passed": len(cases) - len(failing),
            "failed": len(failing),
        },
        "cases": cases,
        "false_exclusion_tally": {
            k: {
                "count": v["count"],
                "confirmed_spurious": v["confirmed"],
                "by_trait": dict(v["by_trait"]),
            }
            for k, v in sorted(
                exclusion_tally.items(), key=lambda kv: -kv[1]["count"]
            )
        },
        "language_contamination": {
            k: dict(v) for k, v in sorted(contamination.items())
        },
        "engine_drift": engine_drift,
        "nondeterministic": nondeterministic,
    }


def _fmt_findings(findings: list[dict[str, Any]]) -> str:
    parts = []
    for f in findings:
        if f["kind"] == "contamination":
            parts.append(f"contamination[{f['category']}]={f['traits']}")
        elif f["kind"] == "recall-miss":
            parts.append(f"recall-miss[{f['category']}]={f['traits']}")
        elif f["kind"] in ("missing-kit", "forbidden-kit"):
            parts.append(f"{f['kind']}={f['kit']}")
        elif f["kind"] == "engine-drift":
            parts.append(f"engine-drift={f['engine']}")
    return "; ".join(parts)


def format_text(report: dict[str, Any]) -> str:
    """Render a human-readable report (for the CLI)."""
    t = report["totals"]
    out: list[str] = ["=" * 72]
    out.append(
        f"KIT-RESOLUTION EVAL  —  {t['cases']} cases: "
        f"{t['passed']} passed, {t['failed']} failed"
    )
    out.append("=" * 72)

    out.append("\n## Failing cases")
    failing = [c for c in report["cases"] if not c["passed"]]
    if not failing:
        out.append("  (none)")
    for c in failing:
        out.append(f"  x {c['id']}  langs={c['inferred_languages']}")
        out.append(f"      {_fmt_findings(c['findings'])}")

    out.append(
        "\n## Catalog-wide false-exclusions "
        "(kits knocked out by inferred traits)"
    )
    tally = report["false_exclusion_tally"]
    if not tally:
        out.append("  (none)")
    for kit, info in tally.items():
        by_trait = ", ".join(f"{tr}x{n}" for tr, n in info["by_trait"].items())
        out.append(
            f"  {kit}: excluded in {info['count']} case(s) "
            f"({info['confirmed_spurious']} confirmed spurious) via {by_trait}"
        )

    out.append("\n## Language contamination (labelled probes)")
    lc = report["language_contamination"]
    if not lc:
        out.append("  (no labelled forbid-language cases)")
    for lang, info in lc.items():
        rate = (
            (info["leaked"] / info["forbidden"] * 100)
            if info["forbidden"]
            else 0
        )
        out.append(
            f"  {lang}: leaked in {info['leaked']}/{info['forbidden']} "
            f"forbidding cases ({rate:.0f}%)"
        )

    if report["engine_drift"]:
        out.append("\n## WARNING engine drift (not 'embedding')")
        out.extend(f"  {cid}" for cid in report["engine_drift"])
    if report["nondeterministic"]:
        out.append("\n## WARNING non-deterministic (traits varied by repeat)")
        out.extend(f"  {cid}" for cid in report["nondeterministic"])
    return "\n".join(out)
