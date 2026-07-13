# Catalog evaluation (`app.eval`)

An in-process evaluation of kit **resolution quality** for whatever catalog an
instance serves. It runs a corpus of tasks through the *real* resolver path and
scores the outcome, so kit authors can judge coverage, hit rate, and — most
usefully — which kits get **silently excluded** because a trait was
over-inferred.

## Why

Trait inference can over-fire. When it infers a language (or framework) a task
never mentioned, every kit whose manifest `excludes` that trait is dropped from
the result with no error. A Python-only task that also infers
`javascript`/`typescript` knocks out kits like `module-code-style-python`. This
harness measures exactly that, catalog-wide.

## The corpus (portable)

* **catalog-derived** — one probe per kit, generated from its manifest. The
  kit's `requires` are the traits that *should* be inferred; its `excludes` are
  the traits that must *not* be. Automatic for any catalog.
* **curated** — a bundled `cases/curated.yaml` of natural, mostly-monolingual
  tasks that pin cross-language contamination, plus full-stack **control** cases
  that legitimately need both languages (to catch over-correction).

## How it runs

For each case the runner calls the same `_infer` (embedding engine + lexical
floor) and `select_kits_v2` a client hits, but **bypasses the `resolve_kits`
wrapper** so the per-user memory nudge and metrics attribution never fire — a
batch eval has no caller and must not pollute anyone's profile. Each record
carries the `engine` that actually ran, so a silent degrade to the lexical floor
is visible in the report (`engine_drift`).

## Report

`build_report` produces: per-case verdicts (contamination / recall-miss /
missing-kit / engine-drift), a **catalog-wide false-exclusion tally** (which
kits were knocked out, by which traits, and how many are confirmed spurious),
language-contamination rates, and engine/determinism sanity.

## Using it

### CLI (local, no server)

Runs against the local `QM_KITS_ROOT` checkout and prints the report; exits
non-zero on any failing case, so it doubles as a CI gate.

```bash
uv run python -m app.eval                 # full corpus, text report
uv run python -m app.eval --cases curated # curated suite only
uv run python -m app.eval --limit 5 --json
```

### API (against a running instance)

Asynchronous — start a job, poll for the report. Auth + vendor `Accept` as for
every `/api` route.

```bash
# start
curl -X POST https://<host>/api/eval/resolution \
  -H 'Authorization: Bearer <token>' \
  -H 'Accept: application/vnd.instructions+json; v=1' \
  -H 'Content-Type: application/json' -d '{"cases":"all"}'
# -> 202 {"job_id":"…","status":"pending",…}

# poll (status becomes "completed", then "report" is present)
curl https://<host>/api/eval/resolution/<job_id> \
  -H 'Authorization: Bearer <token>' \
  -H 'Accept: application/vnd.instructions+json; v=1'
```

## Layout

| file | role |
|---|---|
| `corpus.py` | case model + generators (pure) |
| `report.py` | scoring/analysis over records (pure) |
| `runner.py` | drives cases through the in-process resolver |
| `jobs.py` | in-memory background-job registry |
| `__main__.py` | the local CLI |
| `cases/curated.yaml` | bundled curated suite |

The API layers live outside the package, following the repo's 3-layer
convention: `app/services/eval_service.py` (orchestration) and
`app/routers/eval.py` (`/api/eval/resolution`).
