"""Local CLI for the catalog evaluation — no running server required.

Runs the corpus in-process against the resolver, over whatever kit folder you
point it at, and prints the report. The folder *is* the catalog, so this
evaluates not-yet-deployed kits in any domain.

    uv run python -m app.eval --kits-root ./my-kits      # evaluate a folder
    QM_KITS_ROOT=./my-kits uv run python -m app.eval     # same, via env
    uv run python -m app.eval --cases authored           # only authored cases
    uv run python -m app.eval --limit 5 --json           # smoke run, JSON

Evaluate the impact of an edit by diffing against a saved baseline report:

    uv run python -m app.eval --kits-root ./my-kits --json > before.json
    # ...edit a kit...
    uv run python -m app.eval --kits-root ./my-kits --baseline before.json

Exits non-zero when any case fails, so it doubles as a CI gate.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# The eval only needs a kit root; Settings still requires these auth/server
# values. Default them to inert placeholders so the CLI runs standalone with
# nothing but a kit folder. Real deployments set them for real.
_PLACEHOLDER_ENV = {
    "QM_KEYCLOAK_URL": "https://placeholder.invalid",
    "QM_KEYCLOAK_REALM": "placeholder",
    "QM_RESOURCE_BASE_URL": "http://localhost",
}


def _prepare_env(kits_root: str | None) -> None:
    for key, value in _PLACEHOLDER_ENV.items():
        os.environ.setdefault(key, value)
    if kits_root:
        os.environ["QM_KITS_ROOT"] = str(Path(kits_root).resolve())
    # get_settings() is an lru_cache singleton; drop any cached instance so our
    # env changes take effect on the first read inside the runner.
    from app.config import get_settings

    get_settings.cache_clear()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cases", choices=["catalog", "authored", "all"], default="all"
    )
    p.add_argument(
        "--kits-root",
        default=None,
        help="kit folder to evaluate (else $QM_KITS_ROOT)",
    )
    p.add_argument(
        "--limit", type=int, default=0, help="cap number of cases (0 = all)"
    )
    p.add_argument(
        "--baseline",
        default=None,
        help="a saved JSON report to diff this run against",
    )
    p.add_argument("--json", action="store_true", help="emit JSON, not text")
    args = p.parse_args(argv)

    _prepare_env(args.kits_root)

    # Import after env is prepared (runner reads settings lazily per call).
    from rich.console import Console

    from .render import build_progress, render_diff, render_report
    from .report import diff_reports, format_diff_text, format_text
    from .runner import run_resolution_eval

    # Progress renders to stderr and no-ops when stderr is not a terminal, so
    # stdout (the report / JSON) stays clean and pipeable.
    progress = build_progress(disable=not sys.stderr.isatty())
    task_id = progress.add_task(
        "Loading catalog & embedding model…", total=None
    )

    def on_progress(done: int, total: int) -> None:
        progress.update(
            task_id, description="Evaluating cases", total=total, completed=done
        )

    # When stderr is not a terminal the spinner is disabled, so give a plain
    # one-line heads-up: the first case loads the embedding model, which can
    # take tens of seconds. To stderr, so stdout (report / JSON) stays clean.
    if not sys.stderr.isatty():
        print(
            "Loading catalog & embedding model (first run may take a while)…",
            file=sys.stderr,
            flush=True,
        )

    with progress:
        report = run_resolution_eval(
            which=args.cases, limit=args.limit, on_progress=on_progress
        )
        progress.update(task_id, description="Complete")

    # Rich renders the report only for an interactive stdout; piped/redirected
    # runs keep the byte-for-byte plain text (and JSON) they emit today.
    pretty = sys.stdout.isatty()
    out = Console()

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text())
        diff = diff_reports(baseline, report)
        if args.json:
            print(json.dumps(diff, indent=2))
        elif pretty:
            render_diff(diff, out)
        else:
            print(format_diff_text(diff))
        # A regression (newly failing/missing) is the actionable signal.
        regressed = bool(diff["newly_failing"] or diff["kits"]["newly_missing"])
        return 1 if regressed else 0

    if args.json:
        print(json.dumps(report, indent=2))
    elif pretty:
        render_report(report, out)
    else:
        print(format_text(report))
    return 1 if report["totals"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
