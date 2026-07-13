# Evaluating kits

Quartermaster resolves a task to kits by inferring **traits** from the task text
and ranking every kit against them. *Evaluation* measures how well that works
for your catalog: is each kit reachable for the tasks it should serve, does one
kit block or steal another's resolution, and did a change you just made improve
or regress things?

Evaluation is **domain-agnostic**. It reads whatever kits your catalog contains
and needs no knowledge of your domain — a catalog of baking kits is evaluated
exactly like one of software kits. Nothing domain-specific ships with the
server; the kits (and any cases you author) define the domain.

## Why you evaluate a folder, not a server

Resolution is *relative to the catalog being evaluated*: a task is scored
against the kits that are present. A kit that is not in the catalog cannot be
inferred or ranked. So you evaluate the **folder that contains the kits** — your
working checkout, including kits you have not deployed yet — not a remote server
that does not have them.

`QM_KITS_ROOT` (or `--kits-root`) points the evaluation at that folder, and the
folder *is* the catalog for the run.

## Running it

From a checkout of the server (or its container image), point the CLI at your
kit folder:

```console
$ QM_KITS_ROOT=/path/to/kit-catalog python -m app.eval
$ python -m app.eval --kits-root /path/to/kit-catalog   # equivalent
```

With the published container image and no local Python:

```console
$ docker run --rm --cpus 2 --memory 2g -v "/path/to/kit-catalog:/data/kits" \
    -e QM_KITS_ROOT=/data/kits \
    ghcr.io/exhuma/quartermaster:alpha python -m app.eval
```

The run is resource-heavy — it loads an embedding model and runs inference for
every kit. The `--cpus 2 --memory 2g` flags cap that as a safety measure; raise
or drop them if you want to give the run full power. In a terminal the CLI shows
a live progress bar during the run and a summary report at the end; when its
output is piped or redirected it falls back to plain text.

The **first case** pays a one-time cost: loading the embedding model into
memory, which can take tens of seconds before the progress bar starts moving.
That pause is the model warming up, not a hang — later cases are fast.

Useful flags:

- `--cases {catalog,authored,all}` — which probes to run (default `all`).
- `--limit N` — cap the number of cases for a quick smoke run.
- `--json` — emit the machine-readable report instead of the text summary.
- `--baseline before.json` — diff this run against a saved report
  (see [Evaluating a change](#evaluating-a-change)).

The command exits non-zero when any case fails, so it doubles as a CI gate.

You can also let a coding agent drive it: fetch the `catalog_evaluation` prompt
from Quartermaster (a step-by-step runbook) and ask the agent to run the
evaluation against your kit folder and interpret the report.

## The two kinds of probe

- **Catalog-derived** — one probe per kit, generated automatically from the
  kit's `applicability.json`. The task text is built from the kit's `summary`
  and `optional_signals`; the kit's `requires` are the traits that *should* be
  inferred, and its `excludes` are traits that must *not* be. This gives
  complete per-kit coverage with no authoring.
- **Authored** — natural-language tasks you write in an
  [`eval-cases.yaml`](#eval-cases) at the catalog root, in your own domain's
  words, with the kits and traits you expect. Optional, but the best way to test
  how real user phrasing resolves.

## What the report tells you

Each section names a distinct failure mode.

- **Failing cases** — a case that did not meet its expectation: a kit whose own
  probe did not resolve to it (`missing-kit`), a forbidden trait that was
  inferred anyway (`contamination`), or the inference engine degrading to the
  lexical floor (`engine-drift`).
- **False-exclusions** — kits knocked out because an over-inferred trait matched
  their `excludes`. These kits will *never* resolve while that trait leaks; this
  is usually the highest-impact finding. The report names the offending trait
  and how many are *confirmed spurious* (the trait was labelled must-not-infer).
- **Cross-kit interference** — one kit out-ranking another on the other kit's
  own task. This is how a new or edited kit steals resolution from a sibling.
- **Trait contamination** — for every trait category, how often a forbidden
  trait was inferred across the probes that forbade it.
- **Engine drift / non-determinism** — probes where inference did not use the
  embedding engine, or where repeated runs disagreed.

Not every finding fails a case. Only `missing-kit`, `forbidden-kit`,
`contamination`, and `engine-drift` are fatal. A `recall-miss` (an expected
trait was not inferred) and non-determinism are **advisory** — a `recall-miss`
often *contributes* to a `missing-kit` but is not itself a failure. When
triaging, fix confirmed false-exclusions and runaway traits first, then
`missing-kit`, then contamination and interference; read `recall-miss` as a
clue, not a task. The false-exclusion and interference tables matter even when
every case passes: they reveal kits that are silently unreachable or that
shadow a sibling.

(eval-cases)=

## Authoring `eval-cases.yaml`

Drop a file named `eval-cases.yaml` at the **root of your kit catalog** (next to
the kit directories — it does not clash with kit discovery). Each case is a task
plus what its resolution should and should not contain:

```yaml
cases:
  - task: How do I proof a sourdough loaf overnight?
    expect:
      include:
        capabilities: [proofing]       # traits the task SHOULD infer
      forbid:
        capabilities: [decorating]     # traits it must NOT infer
    kits_include: [kit-sourdough]      # kit that must be recommended
    kits_forbid: [kit-cakes]           # kit that must NOT be (optional)

  - task: What frosting holds up on a layered cake?
    expect:
      forbid:
        capabilities: [proofing]
    kits_include: [kit-cakes]
```

Every field except `task` is optional. The `include`/`forbid` maps are keyed by
trait category. Quartermaster's four categories are fixed: `capabilities` and
`contexts` suit any domain, while `languages` and `frameworks` are
software-oriented and simply left empty by non-software catalogs. Key each
entry under whichever categories your kits actually declare. Run authored cases
alone with `--cases authored`, or together with the per-kit probes using
`--cases all`.

## How authors use it

### Authoring a new kit

Add the kit to your folder and run `python -m app.eval --kits-root .`. Check
that its catalog-derived probe resolves to it (no `missing-kit`) and that it did
not knock out or displace a sibling. Add an authored case for a realistic task
and confirm it recommends the new kit.

### Reviewing an existing catalog

Run `--cases all` over the whole folder and read the false-exclusion and
interference sections: they reveal kits that are unreachable or that shadow one
another, independent of any single kit you are working on.

### Evaluating a change

An edit's impact is a *comparison*, so capture a baseline, edit, then diff:

```console
$ python -m app.eval --kits-root . --json > before.json
# ...edit a kit manifest (requires / excludes / optional_signals) or summary...
$ python -m app.eval --kits-root . --baseline before.json
```

The diff names kits that started or stopped resolving to themselves, kits that
entered or left the false-exclusion set, and rank shifts in a kit's own probe —
the side effects of your edit. It exits non-zero on a regression.

### Full-catalog side-effect review

Reviewing "does adding or changing this kit hurt the rest?" is the same run:
`--cases all` plus the interference and false-exclusion tallies name every kit
that a trait leak or a higher-scoring sibling now displaces.

## Iterating on a kit's manifest

When a probe fails, the fix is almost always in the kit's `applicability.json`
or `summary`:

- A kit **not resolving to itself** usually needs its `requires` traits to be
  present in its `summary`/`optional_signals` so they get inferred, or a
  narrower `requires`.
- A kit **falsely excluding** others means a trait is being over-inferred —
  tighten the summary that seeds it, or reconsider the `excludes`.
- **Interference** means two kits look too alike to inference — sharpen each
  kit's `summary` and `optional_signals` so their traits diverge.

Re-run after each change until the failing cases and false-exclusions are gone.

## Evaluating a running catalog

A deployed Quartermaster instance can evaluate the catalog it currently serves,
for health monitoring:

- The **`evaluate_catalog` MCP tool** — one call returns the report. This is the
  convenient path for an agent connected to a running instance (including a
  local or staging one pointed at your working folder).
- **`POST /api/eval/resolution`** starts an asynchronous job;
  `GET /api/eval/resolution/{job_id}` polls it for the report. Suited to
  dashboards and CI against a running service.

Use those for a *deployed* catalog's health. For kits you are still authoring,
use the local run above — only it sees the not-yet-deployed kits.

See also [Authoring kits](authoring-kits.md) for the manifest fields
(`requires`, `excludes`, `optional_signals`, `summary`) this guide refers to.
