"""Rich presentation for the eval CLI. All ``rich`` imports live here.

``report.py`` stays pure (data only); this module turns its report/diff dicts
into console output. It renders the same fields the plain ``format_text`` /
``format_diff_text`` show, so the two views stay in sync. Only the interactive
CLI uses this; the MCP tool and REST job service render nothing.
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table

from .report import _fmt_findings


def build_progress(*, disable: bool) -> Progress:
    """A progress bar bound to stderr, so it never pollutes stdout output.

    ``disable`` no-ops it (for non-TTY / piped runs), keeping CI logs clean.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=Console(stderr=True),
        transient=False,
        disable=disable,
    )


def _totals_panel(report: dict[str, Any]) -> Panel:
    t = report["totals"]
    failed = t["failed"]
    style = "red" if failed else "green"
    body = (
        f"[bold]{t['cases']}[/bold] cases  ·  "
        f"[green]{t['passed']} passed[/green]  ·  "
        f"[{'red' if failed else 'dim'}]{failed} failed[/]"
    )
    return Panel(body, title="Kit-resolution eval", border_style=style)


def render_report(report: dict[str, Any], console: Console) -> None:
    """Render a full report to ``console`` as panels and tables."""
    console.print(_totals_panel(report))

    failing = [c for c in report["cases"] if not c["passed"]]
    if failing:
        table = Table(title="Failing cases", title_style="bold red")
        table.add_column("case", style="cyan", no_wrap=True)
        table.add_column("langs")
        table.add_column("findings")
        for c in failing:
            table.add_row(
                c["id"],
                ", ".join(c["inferred_languages"]) or "—",
                _fmt_findings(c["findings"]),
            )
        console.print(table)
    else:
        console.print("[green]No failing cases.[/green]")

    tally = report["false_exclusion_tally"]
    if tally:
        table = Table(
            title="Catalog-wide false-exclusions "
            "(kits knocked out by inferred traits)"
        )
        table.add_column("kit", style="cyan")
        table.add_column("cases", justify="right")
        table.add_column("confirmed spurious", justify="right")
        table.add_column("via traits")
        for kit, info in tally.items():
            by_trait = ", ".join(
                f"{tr}×{n}" for tr, n in info["by_trait"].items()
            )
            table.add_row(
                kit,
                str(info["count"]),
                str(info["confirmed_spurious"]),
                by_trait,
            )
        console.print(table)

    interference = report.get("interference_tally") or {}
    if interference:
        table = Table(
            title="Cross-kit interference "
            "(one kit displacing another's resolution)"
        )
        table.add_column("displacer", style="cyan")
        table.add_column("probes", justify="right")
        table.add_column("out-ranks")
        for displacer, info in interference.items():
            displaced = ", ".join(
                f"{kit}×{n}" for kit, n in info["displaces"].items()
            )
            table.add_row(displacer, str(info["count"]), displaced)
        console.print(table)

    contamination = report.get("contamination") or {}
    if contamination:
        table = Table(
            title="Trait contamination (forbidden traits that got inferred)"
        )
        table.add_column("category", style="cyan")
        table.add_column("trait")
        table.add_column("leaked / cases", justify="right")
        table.add_column("rate", justify="right")
        for cat, traits in contamination.items():
            for trait, info in traits.items():
                rate = (
                    (info["leaked"] / info["forbidden"] * 100)
                    if info["forbidden"]
                    else 0
                )
                table.add_row(
                    cat,
                    trait,
                    f"{info['leaked']}/{info['forbidden']}",
                    f"{rate:.0f}%",
                )
        console.print(table)

    if report["engine_drift"]:
        console.print(
            Panel(
                ", ".join(report["engine_drift"]),
                title="WARNING · engine drift (not 'embedding')",
                border_style="yellow",
            )
        )
    if report["nondeterministic"]:
        console.print(
            Panel(
                ", ".join(report["nondeterministic"]),
                title="WARNING · non-deterministic (traits varied by repeat)",
                border_style="yellow",
            )
        )


def _diff_totals_panel(diff: dict[str, Any]) -> Panel:
    bt, ct = diff["totals"]["baseline"], diff["totals"]["candidate"]
    if bt and ct:
        body = (
            f"cases {bt['cases']}→{ct['cases']}  ·  "
            f"passed {bt['passed']}→{ct['passed']}  ·  "
            f"failed {bt['failed']}→{ct['failed']}"
        )
    else:
        body = "(totals unavailable)"
    regressed = bool(diff["newly_failing"] or diff["kits"]["newly_missing"])
    return Panel(
        body,
        title="Kit-resolution eval diff (baseline → candidate)",
        border_style="red" if regressed else "green",
    )


def render_diff(diff: dict[str, Any], console: Console) -> None:
    """Render a before/after diff to ``console``."""
    console.print(_diff_totals_panel(diff))

    def _section(title: str, items: list[Any], style: str) -> None:
        # A styled header line then the items; a single-column table would
        # squeeze these long titles into a narrow column and wrap them badly.
        console.print(f"\n[{style} bold]{title}[/]")
        if items:
            for item in items:
                console.print(f"  {item}")
        else:
            console.print("  [dim](none)[/dim]")

    _section("Regressions — newly failing", diff["newly_failing"], "red")
    _section("Improvements — newly passing", diff["newly_passing"], "green")
    _section(
        "Kits that STOPPED resolving to themselves",
        diff["kits"]["newly_missing"],
        "red",
    )
    _section(
        "Kits that STARTED resolving to themselves",
        diff["kits"]["newly_resolving"],
        "green",
    )
    _section(
        "Kits newly false-excluded", diff["kits"]["newly_excluded"], "red"
    )
    _section(
        "Kits recovered from false-exclusion",
        diff["kits"]["newly_recovered"],
        "green",
    )
    _section(
        "Self-probe rank shifts",
        [
            f"{s['kit']}: rank {s['baseline_rank']} → {s['candidate_rank']}"
            for s in diff["rank_shifts"]
        ],
        "cyan",
    )
    _section("Cases added (candidate only)", diff["added_cases"], "dim")
    _section("Cases removed (baseline only)", diff["removed_cases"], "dim")
