"""
Tests for the in-process eval runner (``app.eval.runner``).

Drives ``run_resolution_eval`` against a small fake catalog with the lexical
floor forced (no embeddings/LLM, deterministic), verifying that inference +
selection + scoring compose end-to-end and that an over-inferred trait produces
a catalog-wide false-exclusion.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from app import resolver
from app.eval.render import render_diff, render_report
from app.eval.report import diff_reports
from app.eval.runner import run_resolution_eval


def _write_kit(base: Path, name: str, summary: str, manifest: dict) -> None:
    instr = base / name / "v1" / "instructions"
    instr.mkdir(parents=True)
    (instr / "invariant.md").write_text("## Invariants\n\nRules.\n")
    (instr / "index.toml").write_text(
        f'summary = "{summary}"\n\n'
        "[[sections]]\n"
        'file = "invariant.md"\n'
        'title = "Invariants"\n'
        'gloss = "Core rules"\n'
        "always_load = true\n"
    )
    (base / name / "applicability.json").write_text(json.dumps(manifest))


def _manifest(summary: str, **over: object) -> dict:
    empty = {
        "languages": [],
        "frameworks": [],
        "capabilities": [],
        "contexts": [],
    }
    base = {
        "kit_type": "module",
        "summary": summary,
        "domains": ["backend"],
        "languages": [],
        "frameworks": [],
        "contexts": [],
        "requires": dict(empty),
        "excludes": dict(empty),
        "optional_signals": [],
        "related_kits": [],
        "priority": 70,
    }
    base.update(over)
    return base


@pytest.fixture()
def eval_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write_kit(
        tmp_path,
        "mod-py",
        "Python backend service guidance",
        _manifest(
            "Python backend service guidance",
            languages=["python"],
            contexts=["backend"],
            requires={
                "languages": ["python"],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
        ),
    )
    _write_kit(
        tmp_path,
        "mod-vue",
        "Vue frontend component library",
        _manifest(
            "Vue frontend component library",
            frameworks=["vue"],
            contexts=["frontend"],
            requires={
                "languages": [],
                "frameworks": ["vue"],
                "capabilities": [],
                "contexts": [],
            },
            # Trips on any python task — the exclusion we want to observe.
            excludes={
                "languages": ["python"],
                "frameworks": [],
                "capabilities": [],
                "contexts": [],
            },
        ),
    )
    monkeypatch.setattr(
        "app.kits.get_settings",
        lambda: type("S", (), {"kits_root": tmp_path})(),
    )
    # Force the lexical floor: deterministic, no model download.
    monkeypatch.setattr(resolver, "_build_trait_engines", lambda: [])
    return tmp_path


def _case(report: dict, cid: str) -> dict:
    return next(c for c in report["cases"] if c["id"] == cid)


def test_runner_scores_catalog(eval_catalog: Path) -> None:
    report = run_resolution_eval(which="catalog")
    assert report["catalog_size"] == 2
    assert report["totals"]["cases"] == 2
    # Lexical floor was forced, so every case reports that engine.
    assert all(c["engine"] == "lexical" for c in report["cases"])


def test_runner_selects_matching_kit(eval_catalog: Path) -> None:
    report = run_resolution_eval(which="catalog")
    py = _case(report, "catalog::mod-py")
    # mod-py's own task mentions "python" -> it must be selected (no miss).
    assert not any(f["kind"] == "missing-kit" for f in py["findings"])


def test_runner_surfaces_false_exclusion(eval_catalog: Path) -> None:
    report = run_resolution_eval(which="catalog")
    py = _case(report, "catalog::mod-py")
    # Inferring python excludes mod-vue (excludes.languages=[python]).
    excluded = {fx["kit"] for fx in py["false_exclusions"]}
    assert "mod-vue" in excluded
    assert "mod-vue" in report["false_exclusion_tally"]


def test_runner_loads_author_cases(eval_catalog: Path) -> None:
    # An optional eval-cases.yaml at the catalog root supplies domain cases.
    (eval_catalog / "eval-cases.yaml").write_text(
        "cases:\n"
        "  - id: my-python-task\n"
        "    task: build a python backend service\n"
        "    kits_include: [mod-py]\n"
    )
    report = run_resolution_eval(which="authored")
    ids = [c["id"] for c in report["cases"]]
    assert ids == [
        "authored::my-python-task"
    ]  # only authored, no catalog probes
    case = _case(report, "authored::my-python-task")
    # "python" is inferred (lexical) -> mod-py selected -> no missing-kit.
    assert not any(f["kind"] == "missing-kit" for f in case["findings"])


def test_runner_reports_progress(eval_catalog: Path) -> None:
    calls: list[tuple[int, int]] = []
    report = run_resolution_eval(
        which="catalog", on_progress=lambda done, total: calls.append(
            (done, total)
        )
    )
    n = report["totals"]["cases"]
    assert n == 2
    # Fires once with (0, N) before the loop, then after each case.
    assert calls[0] == (0, n)
    assert calls[-1] == (n, n)
    assert len(calls) == n + 1


def test_render_report_smoke(eval_catalog: Path) -> None:
    report = run_resolution_eval(which="catalog")
    console = Console(file=io.StringIO(), width=100)
    render_report(report, console)
    text = console.file.getvalue()
    assert "passed" in text
    assert "failed" in text


def test_render_diff_smoke(eval_catalog: Path) -> None:
    report = run_resolution_eval(which="catalog")
    diff = diff_reports(report, report)  # self-diff: no regressions
    console = Console(file=io.StringIO(), width=100)
    render_diff(diff, console)
    text = console.file.getvalue()
    assert "candidate" in text


def test_cli_warns_about_model_load_on_non_tty(
    eval_catalog: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # In a non-TTY run the rich spinner is disabled, so the CLI must still
    # announce the model-load pause — on stderr, leaving stdout's report clean.
    from app.eval import __main__ as cli

    monkeypatch.setattr("sys.stderr.isatty", lambda: False)
    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    cli.main(["--cases", "catalog"])

    captured = capsys.readouterr()
    assert "first run may take a while" in captured.err
    assert "first run may take a while" not in captured.out
    # stdout still carries the plain-text report, uncorrupted by the notice.
    assert "KIT-RESOLUTION EVAL" in captured.out
