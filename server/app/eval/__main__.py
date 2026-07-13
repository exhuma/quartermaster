"""Local CLI for the catalog evaluation — no running server required.

Runs the corpus in-process against the resolver and prints the report. Useful
for kit authors iterating on a local catalog checkout.

    uv run python -m app.eval                      # full corpus, text report
    uv run python -m app.eval --cases curated      # just the curated suite
    uv run python -m app.eval --limit 5 --json     # smoke run, JSON output

Exits non-zero when any case fails, so it doubles as a CI gate.
"""

from __future__ import annotations

import argparse
import json
import sys

from .report import format_text
from .runner import run_resolution_eval


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cases", choices=["catalog", "curated", "all"], default="all"
    )
    p.add_argument(
        "--limit", type=int, default=0, help="cap number of cases (0 = all)"
    )
    p.add_argument(
        "--json", action="store_true", help="emit the report as JSON"
    )
    args = p.parse_args(argv)

    report = run_resolution_eval(which=args.cases, limit=args.limit)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))
    return 1 if report["totals"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
