"""Scoring and analysis over kit-resolution records. Pure, no I/O.

A *record* is one resolution outcome:

    {
      "id", "source", "engine",
      "inferred_traits": {languages, frameworks, capabilities, contexts},
      "kits": [{"name", "score"}, ...],     # kits that survived selection
      "expect": {include, forbid, kits_include, kits_forbid},
    }

``build_report`` turns a list of records + the catalog manifests into a
structured report: per-case verdicts, catalog-wide false-exclusions, cross-kit
interference, trait contamination, and engine/determinism sanity.
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


# Number of top kits credited with "capturing" a kit's slot when the kit is
# absent from its own probe entirely.
_DISPLACER_CAP = 3


def self_probe_displacement(
    rec: dict[str, Any],
) -> tuple[str | None, int | None, list[str]]:
    """For a kit's own catalog probe, who out-ranks it?

    Returns ``(own_kit, self_rank, displacers)``. ``self_rank`` is the kit's
    index in its own ranked results (0 = top), or ``None`` when it is absent.
    ``displacers`` are the kits that ranked above it (or the top few that
    captured its slot when it is absent). All ``(None, None, [])`` for cases
    that are not single-kit catalog self-probes.
    """
    if rec.get("source") != "catalog":
        return None, None, []
    include = (rec.get("expect") or {}).get("kits_include") or []
    if len(include) != 1:
        return None, None, []
    own = include[0]
    ranked = [k.get("name") for k in (rec.get("kits") or [])]
    if own in ranked:
        idx = ranked.index(own)
        return own, idx, ranked[:idx]
    return own, None, ranked[:_DISPLACER_CAP]


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
    # category -> trait -> {forbidden, leaked}; domain-agnostic (not just langs)
    contamination: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: {"forbidden": 0, "leaked": 0})
    )
    engine_drift: list[str] = []
    nondeterministic: list[str] = []
    # displacer kit -> {displaced kit: count}
    interference: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    for cid, recs in by_id.items():
        primary = recs[0]
        findings = verdict_for(primary)
        fexcl = false_exclusions(primary, excludes_by_kit)

        own, self_rank, displacers = self_probe_displacement(primary)
        for displacer in displacers:
            if displacer and own:
                interference[displacer][own] += 1
        for fe in fexcl:
            tally = exclusion_tally[fe["kit"]]
            tally["count"] += 1
            if fe["confirmed_spurious"]:
                tally["confirmed"] += 1
            for _cat, trait in fe["offending"]:
                tally["by_trait"][trait] += 1

        # contamination accounting across every trait category
        inferred = primary.get("inferred_traits") or {}
        forbid = primary.get("expect", {}).get("forbid") or {}
        for cat, traits in forbid.items():
            inf = set(inferred.get(cat) or [])
            for trait in traits:
                contamination[cat][trait]["forbidden"] += 1
                if trait in inf:
                    contamination[cat][trait]["leaked"] += 1
        inferred_langs = set(inferred.get("languages") or [])

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
                "self_kit": own,
                "self_rank": self_rank,
                "displaced_by": displacers if self_rank != 0 else [],
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
        "contamination": {
            cat: {
                trait: dict(counts) for trait, counts in sorted(traits.items())
            }
            for cat, traits in sorted(contamination.items())
        },
        "interference_tally": {
            displacer: {
                "count": sum(displaced.values()),
                "displaces": dict(displaced),
            }
            for displacer, displaced in sorted(
                interference.items(),
                key=lambda kv: -sum(kv[1].values()),
            )
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

    out.append(
        "\n## Cross-kit interference (one kit displacing another's resolution)"
    )
    interference = report.get("interference_tally") or {}
    if not interference:
        out.append("  (none)")
    for displacer, info in interference.items():
        displaced = ", ".join(
            f"{kit}x{n}" for kit, n in info["displaces"].items()
        )
        out.append(
            f"  {displacer}: out-ranks {info['count']} probe(s): {displaced}"
        )

    out.append("\n## Trait contamination (forbidden traits that got inferred)")
    contamination = report.get("contamination") or {}
    if not contamination:
        out.append("  (no labelled forbid-trait cases)")
    for cat, traits in contamination.items():
        for trait, info in traits.items():
            rate = (
                (info["leaked"] / info["forbidden"] * 100)
                if info["forbidden"]
                else 0
            )
            out.append(
                f"  {cat}:{trait}: leaked in "
                f"{info['leaked']}/{info['forbidden']} cases ({rate:.0f}%)"
            )

    if report["engine_drift"]:
        out.append("\n## WARNING engine drift (not 'embedding')")
        out.extend(f"  {cid}" for cid in report["engine_drift"])
    if report["nondeterministic"]:
        out.append("\n## WARNING non-deterministic (traits varied by repeat)")
        out.extend(f"  {cid}" for cid in report["nondeterministic"])
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# before/after regression diff (evaluate the impact of a kit change)
# --------------------------------------------------------------------------- #
def _pass_map(report: dict[str, Any]) -> dict[str, bool]:
    return {c["id"]: bool(c["passed"]) for c in report.get("cases", [])}


def _self_resolution_map(report: dict[str, Any]) -> dict[str, bool]:
    """kit -> did its own catalog probe resolve to it (no missing-kit)."""
    out: dict[str, bool] = {}
    for c in report.get("cases", []):
        kit = c.get("self_kit")
        if not kit:
            continue
        missing = any(
            f.get("kind") == "missing-kit" and f.get("kit") == kit
            for f in c.get("findings", [])
        )
        out[kit] = not missing
    return out


def _self_rank_map(report: dict[str, Any]) -> dict[str, int | None]:
    return {
        c["self_kit"]: c.get("self_rank")
        for c in report.get("cases", [])
        if c.get("self_kit")
    }


def diff_reports(
    baseline: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Compare two reports to show what a kit change moved.

    Surfaces cases that flipped pass/fail, kits that started/stopped resolving
    to themselves, kits that entered/left the false-exclusion set, and rank
    shifts in a kit's own probe. Pure over the two report dicts.
    """
    b_pass, c_pass = _pass_map(baseline), _pass_map(candidate)
    common_ids = b_pass.keys() & c_pass.keys()

    b_res, c_res = (
        _self_resolution_map(baseline),
        _self_resolution_map(candidate),
    )
    common_kits = b_res.keys() & c_res.keys()

    b_excl = set(baseline.get("false_exclusion_tally") or {})
    c_excl = set(candidate.get("false_exclusion_tally") or {})

    b_rank, c_rank = _self_rank_map(baseline), _self_rank_map(candidate)
    rank_shifts = [
        {"kit": k, "baseline_rank": b_rank[k], "candidate_rank": c_rank[k]}
        for k in sorted(b_rank.keys() & c_rank.keys())
        if b_rank[k] != c_rank[k]
    ]

    return {
        "totals": {
            "baseline": baseline.get("totals"),
            "candidate": candidate.get("totals"),
        },
        "newly_failing": sorted(
            i for i in common_ids if b_pass[i] and not c_pass[i]
        ),
        "newly_passing": sorted(
            i for i in common_ids if not b_pass[i] and c_pass[i]
        ),
        "kits": {
            "newly_missing": sorted(
                k for k in common_kits if b_res[k] and not c_res[k]
            ),
            "newly_resolving": sorted(
                k for k in common_kits if not b_res[k] and c_res[k]
            ),
            "newly_excluded": sorted(c_excl - b_excl),
            "newly_recovered": sorted(b_excl - c_excl),
        },
        "rank_shifts": rank_shifts,
        "added_cases": sorted(c_pass.keys() - b_pass.keys()),
        "removed_cases": sorted(b_pass.keys() - c_pass.keys()),
    }


def format_diff_text(diff: dict[str, Any]) -> str:
    """Render a before/after diff for the CLI."""
    bt, ct = diff["totals"]["baseline"], diff["totals"]["candidate"]
    out: list[str] = [
        "=" * 72,
        "KIT-RESOLUTION EVAL DIFF (baseline -> candidate)",
    ]
    if bt and ct:
        out.append(
            f"  cases {bt['cases']}->{ct['cases']}, "
            f"passed {bt['passed']}->{ct['passed']}, "
            f"failed {bt['failed']}->{ct['failed']}"
        )
    out.append("=" * 72)

    def _section(title: str, items: list[Any]) -> None:
        out.append(f"\n## {title}")
        if not items:
            out.append("  (none)")
        else:
            out.extend(f"  {i}" for i in items)

    _section("Regressions — newly failing cases", diff["newly_failing"])
    _section("Improvements — newly passing cases", diff["newly_passing"])
    _section(
        "Kits that STOPPED resolving to themselves",
        diff["kits"]["newly_missing"],
    )
    _section(
        "Kits that STARTED resolving to themselves",
        diff["kits"]["newly_resolving"],
    )
    _section("Kits newly false-excluded", diff["kits"]["newly_excluded"])
    _section(
        "Kits recovered from false-exclusion", diff["kits"]["newly_recovered"]
    )
    _section(
        "Self-probe rank shifts",
        [
            f"{s['kit']}: rank {s['baseline_rank']} -> {s['candidate_rank']}"
            for s in diff["rank_shifts"]
        ],
    )
    _section("Cases added (candidate only)", diff["added_cases"])
    _section("Cases removed (baseline only)", diff["removed_cases"])
    return "\n".join(out)
