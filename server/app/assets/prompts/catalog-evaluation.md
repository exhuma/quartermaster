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
2. Run the evaluation over that folder **with the published container image**.
   Do NOT assume `python` or a Quartermaster checkout exists in your
   environment — run it via `docker` (or `podman`), which needs neither:
   ```
   docker run --rm --cpus 2 --memory 2g -v "<catalog-root>:/data/kits" -e QM_KITS_ROOT=/data/kits ghcr.io/exhuma/quartermaster:alpha python -m app.eval --cases all
   ```
   Only if you already have a Quartermaster **source checkout** with Python and
   its dependencies installed may you instead run it directly:
   `QM_KITS_ROOT=<catalog-root> python -m app.eval --cases all`.

   The run is resource-heavy; `--cpus 2 --memory 2g` caps it (drop the flags for
   full power). Add `--json` to capture the report, `--limit N` for a quick
   smoke run. The first case loads the embedding model, so expect a pause of
   tens of seconds before results appear — that is the model warming up, not a
   hang.
3. Read the report and interpret it — do not just restate the section titles.

   **The finding kinds, by severity.** Only four kinds *fail* a case; the rest
   are advisory. Do not report an advisory finding as a failure.
   - Fatal (a case with any of these is a failure):
     - `missing-kit` — a kit's own probe did not surface the kit itself.
     - `forbidden-kit` — a kit that must *not* be recommended was.
     - `contamination` — a must-not-infer trait was inferred anyway.
     - `engine-drift` — inference fell off the embedding engine to the lexical
       floor (usually a setup problem: the embedding model is unavailable).
   - Advisory (never fail a case; mention only as context):
     - `recall-miss` — an expected trait was not inferred. It weakens a kit's
       score and often *contributes* to a `missing-kit`, but on its own it is
       not a failure.
     - non-determinism — repeated runs disagreed on inferred traits.

   **The catalog-wide tables** (they surface problems the pass/fail count hides
   — a "19/21 passed" catalog can still be fragile):
   - **False-exclusions** — kits knocked out because an over-inferred trait
     matched their `excludes`; those kits will *never* resolve while that trait
     leaks. Usually the highest-impact finding. Each row shows the offending
     trait and a *confirmed spurious* count: how many of those exclusions are
     *proven* wrong (the trait was labelled must-not-infer in that case). A
     trait that excludes many kits across the catalog is a runaway trait —
     prioritise it even if only a few exclusions are confirmed.
   - **Cross-kit interference** — one kit out-ranking another on the other
     kit's own probe: how a new or broad kit steals resolution from a sibling.
   - **Trait contamination** — per category, how often a forbidden trait was
     inferred across the probes that forbade it.

   **Triage order — explain and fix in this order:** (1) runaway / confirmed
   false-exclusions and over-inferred traits, (2) `missing-kit` (from
   recall-misses and/or a displacer out-ranking the kit), (3) `contamination`,
   (4) interference; treat `recall-miss` and non-determinism as advisory
   signals that inform 1–3, not as items to fix on their own.

   **Map each finding to a fix** (all edits land in a kit's
   `applicability.json` or `summary`):
   - not resolving to itself (`missing-kit` / `recall-miss`) → add the missing
     `requires` traits' vocabulary to the kit's `summary`/`optional_signals`,
     or narrow an over-broad `requires`.
   - false-excluding others → an over-inferred trait; tighten the *source*
     kit's `summary`/`optional_signals` so the trait stops leaking, or
     reconsider the excluded kit's `excludes`.
   - interference → sharpen both kits' `summary` so their traits diverge; lower
     a too-broad "reference"/"project" kit's `priority`.
   - `engine-drift` → not a manifest problem; the embedding model is
     unavailable — fix the environment (install the `embeddings` extra / use
     the container image), then re-run.

   Then **explain the findings to the author** in these terms — what failed,
   why, and the concrete manifest edits you recommend — and offer to apply an
   edit and re-run (capture a baseline first, per step 5, so you can diff the
   effect).
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
5. To evaluate a *change*, capture a baseline first, edit, then diff. Mount the
   current directory too (`-v "$PWD:/work"`) so the baseline file is reachable
   inside the container on the second run:
   ```
   docker run --rm -v "<catalog-root>:/data/kits" -v "$PWD:/work" -e QM_KITS_ROOT=/data/kits ghcr.io/exhuma/quartermaster:alpha python -m app.eval --json > before.json
   # …edit a kit's applicability.json (requires / excludes / optional_signals) or summary…
   docker run --rm -v "<catalog-root>:/data/kits" -v "$PWD:/work" -e QM_KITS_ROOT=/data/kits ghcr.io/exhuma/quartermaster:alpha python -m app.eval --baseline /work/before.json
   ```
   (With a local checkout: `python -m app.eval --kits-root <root> --json >
   before.json`, then `… --baseline before.json`.) The diff names kits that
   started or stopped resolving, new false-exclusions, and rank shifts — the
   side effects of your edit.
6. Iterate: tighten a kit's `requires` / `excludes`, and sharpen its `summary`
   and `optional_signals` so its traits are inferred for the right tasks and not
   the wrong ones. Re-run until failing cases and false-exclusions are gone.

A running Quartermaster instance can also evaluate the catalog it currently
serves — via the `evaluate_catalog` tool (one call returns the report) or the
`POST /api/eval/resolution` job. Use those for a deployed catalog's health; use
the local run above for kits you are still authoring.
