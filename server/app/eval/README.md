# Catalog evaluation (`app.eval`)

In-process, **domain-agnostic** evaluation of kit *resolution quality* for
whatever catalog an instance (or a local folder) serves. It runs a corpus of
tasks through the real resolver path and scores the outcome, so kit authors can
judge coverage and hit rate, spot kits that get silently excluded by
over-inferred traits, and see one kit displacing another.

> **Author guide:** [`docs/user/evaluating-kits.md`](../../../docs/user/evaluating-kits.md)
> is the authoritative, task-oriented documentation. This README is a
> code-level quick reference.

## Model

The active kit root **is** the catalog, so this evaluates not-yet-deployed kits
in any domain — inference (vocab + embeddings) is built over whatever kits the
folder contains. Nothing domain-specific ships here; only the code.

Corpus sources (`corpus.py`):
- **catalog-derived** — one probe per kit from its manifest (`requires` =
  should-infer, `excludes` = must-not-infer).
- **authored** — an optional `eval-cases.yaml` at the catalog root, written by
  the domain owner.

The runner (`runner.py`) reproduces the real `_infer` + `select_kits_v2` path
but bypasses the `resolve_kits` wrapper, so a caller-less batch run never fires
the per-user memory nudge or metrics attribution. `report.py` (pure) scores
records into per-case verdicts, a catalog-wide false-exclusion tally, cross-kit
interference, and trait contamination; `diff_reports` compares two reports.

## Surfaces

- **CLI** — `python -m app.eval` (local, no server). `--kits-root PATH`,
  `--cases {catalog,authored,all}`, `--limit N`, `--json`, `--baseline
  report.json`. Non-zero exit on failure (CI gate).
- **MCP tool** — `evaluate_catalog(cases, limit)` runs over the instance's own
  catalog and returns the report (one call, for agents on a running instance).
- **MCP prompt** — `catalog_evaluation`, a domain-neutral runbook for an
  author's agent to drive the whole lifecycle.
- **REST job** — `POST /api/eval/resolution` + `GET /api/eval/resolution/{id}`
  (async, for humans/dashboards), via `app/services/eval_service.py` and
  `app/routers/eval.py`.

## Layout

| file | role |
|---|---|
| `corpus.py` | case model + generators (pure) |
| `report.py` | scoring, interference, and `diff_reports` (pure) |
| `runner.py` | drives cases through the in-process resolver |
| `jobs.py` | in-memory background-job registry |
| `__main__.py` | the local CLI |
