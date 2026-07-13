"""Drive the evaluation corpus through the in-process resolver.

For each case this reproduces the *real* trait-inference + selection path a
client hits — ``_infer`` (embedding engine, with the lexical floor) followed by
``select_kits_v2`` — but deliberately bypasses the ``resolve_kits`` wrapper so
the per-user memory nudge and metrics attribution never fire. A batch eval has
no authenticated caller and must not pollute anyone's memory profile.

The result is a report (see ``report.build_report``) plus an ``engine`` field
naming the inference engine that actually ran, so a caller can tell when the
embedding model silently degraded to the lexical floor.
"""

from __future__ import annotations

from typing import Any

from app import kits as kits_mod
from app.kits import list_catalog_v2, select_kits_v2
from app.resolver import _infer
from app.traits import load_vocabulary

from .corpus import Case, build_cases
from .report import build_report

# Bound the per-case candidate list generously; selection is cheap and the
# report only cares about which kits survived, not their order past the cut.
_SELECT_LIMIT = 50


def _resolve_case(case: Case, vocab: Any) -> dict[str, Any]:
    """Run one case through inference + selection; return a record."""
    _engine, inferred = _infer(case.task, vocab)
    selection = select_kits_v2(
        languages=inferred.languages,
        frameworks=inferred.frameworks,
        capabilities=inferred.capabilities,
        contexts=inferred.contexts,
        limit=_SELECT_LIMIT,
    )
    kits = [
        {"name": c.get("name"), "score": c.get("score")}
        for c in selection.get("candidates", [])
    ]
    meta = case.to_meta()
    return {
        "id": case.id,
        "task": case.task,
        "source": case.source,
        "engine": inferred.engine,
        "inferred_traits": {
            "languages": inferred.languages,
            "frameworks": inferred.frameworks,
            "capabilities": inferred.capabilities,
            "contexts": inferred.contexts,
        },
        "kits": kits,
        "expect": meta["expect"],
    }


def run_resolution_eval(
    which: str = "all",
    limit: int = 0,
) -> dict[str, Any]:
    """Run the corpus in-process and return a scored report.

    :param which: case set — ``catalog`` | ``authored`` | ``all``.
    :param limit: cap the number of cases (0 = all). Useful for smoke runs.
    """
    catalog = list_catalog_v2()
    vocab = load_vocabulary()
    kits_root = kits_mod.get_settings().kits_root
    cases = build_cases(which, catalog, kits_root)
    if limit:
        cases = cases[:limit]

    records = [_resolve_case(case, vocab) for case in cases]
    report = build_report(records, catalog)
    report["params"] = {"cases": which, "limit": limit}
    report["catalog_size"] = len(catalog)
    return report
