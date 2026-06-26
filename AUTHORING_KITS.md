# Authoring kits

A **kit** is a versioned, agent-facing guide plus the metadata Quartermaster
uses to discover, rank, and serve it. Kits live in your **kit-catalog repo**
(not here) — the directory `QM_KITS_ROOT` points at. Quartermaster validates
every kit on load and on write, so a malformed kit is rejected rather than
served.

## Layout

```
<kit-name>/
  applicability.json        # selector metadata (required)
  CHANGELOG.md              # version history (required)
  v1/                       # one folder per MAJOR version
    instructions/
      index.toml            # section manifest (required)
      invariant.md          # always-load core: invariants / prohibited patterns
      <section>.md          # one file per section
    README.md               # human doc / adopter template
    workflows/ scripts/     # optional supporting files
  v2/ ...                   # added only on a breaking change
```

A kit is discovered only when `<kit-name>/v<N>/instructions/index.toml`
exists (`N` a positive integer). The kit name is the top-level folder.

## `instructions/index.toml` — the sections

Guides are **fragmented into sections** so an agent can load only what a task
needs. Declare a one-sentence `summary` and an ordered `[[sections]]` array:

```toml
summary = "Adds PostgreSQL + SQLAlchemy + Alembic with one session per request."

[[sections]]
file = "invariant.md"        # basename in this dir; must exist
title = "Invariants"         # non-empty
gloss = "Non-negotiables: Alembic owns schema, one session per request."
always_load = true           # boolean (default false)

[[sections]]
file = "setup.md"
title = "Setup"
gloss = "Step-by-step: install deps, init Alembic, wire the session factory."
always_load = false
```

Rules:
- The **section id** an agent passes to `get_kit(sections=[…])` is the file
  **stem** (`invariant.md` → `invariant`). Ids must be unique.
- `gloss` (≤ ~100 chars, one line) and `summary` (≤ ~150 chars, one sentence)
  are **purpose-written descriptions, not a hard cut of the body** — no
  trailing `…`, no mid-sentence fragments, no bare `Overview` placeholders.
- Front-load invariants and prohibited patterns into `always_load = true`
  sections; isolate heavy code templates into their own (skippable) sections.

## `applicability.json` — the selector metadata

Drives trait-based ranking (`select_kits`/`explain_kit_candidate`). **All**
fields below are required:

```json
{
  "kit_type": "module",
  "summary": "PostgreSQL + SQLAlchemy + Alembic data layer.",
  "domains": ["database"],
  "languages": ["python"],
  "frameworks": ["sqlalchemy", "alembic"],
  "contexts": ["backend"],
  "requires":  { "languages": ["python"], "frameworks": [], "capabilities": [], "contexts": [] },
  "excludes":  { "languages": [], "frameworks": [], "capabilities": [], "contexts": [] },
  "optional_signals": ["postgres", "asyncpg"],
  "related_kits": ["stack-fastapi-vuetify"],
  "priority": 50
}
```

- `kit_type` — one of `module`, `stack`, `release`.
- `requires` / `excludes` — objects that **must contain all four trait keys**:
  `languages`, `frameworks`, `capabilities`, `contexts` (each a string list,
  empty is fine). Note: the trait category is `capabilities`, distinct from the
  top-level `domains` field. A satisfied `requires` boosts the kit; any matched
  `excludes` makes it ineligible.
- `priority` — integer base score (higher is preferred).
- `domains`, `languages`, `frameworks`, `contexts`, `optional_signals`,
  `related_kits` — string lists used for matching/ranking.

## Versioning

Semantic, encoded in the folder structure:

| Change | Action |
|---|---|
| Breaking (large code-churn for adopters) | new `v<N>/` folder + `## v<N>.0.0` changelog entry |
| New feature / clarification | changelog entry only (minor) |
| Fix / typo / section reshuffle | changelog entry only (patch) |

Always add a `CHANGELOG.md` entry. Headings **must** match `## v<version>`
(e.g. `## v1.2.0`) so `compare_kit_versions` can parse them.

## Validate before you ship

Quartermaster enforces all of the above when it loads or writes a kit:
- Editing files directly or over WebDAV (`/dav`): a bad kit simply fails to
  load — watch the server logs.
- Via the REST API (`PUT /api/kits/...`): writes are validated **before**
  commit and rejected with `422` if invalid, so the catalog can't be left
  unloadable.
