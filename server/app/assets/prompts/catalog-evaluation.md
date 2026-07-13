Use this runbook to evaluate how well a Quartermaster kit catalog *resolves* —
whether each kit is reachable for the tasks it should serve, and whether kits
interfere with one another. It works for any catalog in any domain; the kits
themselves define the domain.

## When to run it

- You authored or edited a kit and want to know if resolution improved or broke.
- You are reviewing an existing catalog for coverage and hit rate.
- You suspect one kit is shadowing another (a task resolves to the wrong kit).

## Why you evaluate the local folder

Resolution is *relative to the catalog being evaluated*: trait inference scores a
task against every kit in the catalog. A kit that is not in the catalog cannot be
inferred or selected. So evaluate against the folder that actually contains the
kits — including not-yet-deployed ones — not a remote server that lacks them.

## Steps

1. Locate the kit-catalog root: the folder whose subdirectories each hold an
   `applicability.json` and a `v<N>/instructions/` directory.
2. Run the evaluation over that folder:
   - `QM_KITS_ROOT=<catalog-root> python -m app.eval --cases all`, or
   - the container form:
     `docker run --rm -v "<catalog-root>:/data/kits" -e QM_KITS_ROOT=/data/kits <quartermaster-image> python -m app.eval --cases all`
   Add `--json` to capture the report, `--limit N` for a quick smoke run.
3. Read the report. Each section names a distinct failure mode:
   - **Failing cases** — a kit whose own probe did not resolve to it
     (`missing-kit`), a forbidden trait that got inferred (`contamination`), or
     the inference engine degraded to the lexical floor (`engine-drift`).
   - **False-exclusions** — kits knocked out because an over-inferred trait
     matched their `excludes`. Those kits will *never* resolve while that trait
     leaks. This is usually the highest-impact finding.
   - **Cross-kit interference** — one kit out-ranking another on the other kit's
     own task: how a new or edited kit steals resolution from a sibling.
   - **Trait contamination** — forbidden traits that were inferred anyway.
4. To exercise real user phrasing, add an `eval-cases.yaml` at the catalog root
   with natural-language tasks in *your* domain and the kits/traits you expect,
   then re-run. Schema:
   ```
   cases:
     - task: <a natural task in your domain>
       expect:
         include: { capabilities: [<trait the task should infer>] }
         forbid:  { capabilities: [<trait it must not infer>] }
       kits_include: [<kit that should be recommended>]
   ```
5. To evaluate a *change*, capture a baseline first, edit, then diff:
   - `python -m app.eval --kits-root <root> --json > before.json`
   - …edit a kit's `applicability.json` (`requires` / `excludes` /
     `optional_signals`) or its `summary`…
   - `python -m app.eval --kits-root <root> --baseline before.json`
   The diff names kits that started or stopped resolving, new false-exclusions,
   and rank shifts — the side effects of your edit.
6. Iterate: tighten a kit's `requires` / `excludes`, and sharpen its `summary`
   and `optional_signals` so its traits are inferred for the right tasks and not
   the wrong ones. Re-run until failing cases and false-exclusions are gone.

A running Quartermaster instance can also evaluate the catalog it currently
serves — via the `evaluate_catalog` tool (one call returns the report) or the
`POST /api/eval/resolution` job. Use those for a deployed catalog's health; use
the local run above for kits you are still authoring.
