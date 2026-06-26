# Recommended `AGENTS.md` guidance for Quartermaster-backed repos

This page explains the guidance you should put in a repository's `AGENTS.md`
(or `CLAUDE.md`) so a coding agent discovers applicable instruction kits from
Quartermaster *reliably* and *token-efficiently*.

It is **not** about authoring kits (see [AUTHORING_KITS.md](AUTHORING_KITS.md))
or about working inside this server's own codebase (see
[`.ai/rules.md`](.ai/rules.md)). It is the short briefing a downstream project
gives its agents so they drive Quartermaster well.

> The detailed routine lives in **one** place — Quartermaster's
> `trait_selection_bootstrap` prompt (fetch it with `list_prompts` →
> `get_prompt`). Your `AGENTS.md` should *point at* that prompt, not restate
> it, so the guidance can evolve server-side without every repo drifting out
> of date.

## Why this guidance exists

We observed a real failure mode: an agent asked Quartermaster for kits using
generic or invented traits — `auth`, `api`, `internal-service`, or `kubernetes`
as a *context* rather than a *framework*. Quartermaster had relevant kits, but
the query did not line up with its published vocabulary, so selection scored
poorly and the agent wrongly concluded nothing applied. The guidance below
prevents that, at minimal token cost.

### 1. Quartermaster's published vocabulary is the source of truth

Selection matches against a fixed, advertised vocabulary of `languages`,
`frameworks`, `capabilities`, and `contexts` (see `list_available_traits`).
Only those values score. A plausible-sounding trait the agent makes up
(`internal-service`, `microservice`, `auth` when the catalog says `oidc`)
simply does not match — the kit is there, but the query misses it. Treating the
advertised vocabulary as authoritative is the single highest-leverage habit.

### 2. Free-form user wording usually needs normalization first

Users describe intent in their own words: "a REST API", "deployed on k8s",
"needs login", "with logging". None of those are guaranteed to be trait values.
The agent's job is to *normalize* each concern onto a supported trait before
calling `select_kits` — for example:

| User says…            | Normalizes to…                                          |
|-----------------------|---------------------------------------------------------|
| "REST API"            | framework `fastapi` + capability `rest-api`/`api-design`|
| "deployed on k8s"     | context `deploy`                                         |
| "needs login / auth"  | capability `auth` → resolve to `oidc` / `local-auth`    |
| "logging"             | capability `observability` / `correlation-id`           |
| "health checks"       | capability `health-checks` / `healthz`                  |
| "runtime config"      | capability `runtime-config` / `env-vars`                |
| "audit logging"       | capability `security` (+ `observability`)               |

When a request introduces a new runtime, deployment, or capability concern the
agent has not yet mapped, it should re-check `list_available_traits` rather than
guess.

### 3. Low coverage means *broaden and retry*, not "no kit applies"

`select_kits` returns `coverage` and a `broadening_recommended` flag. Low
coverage usually means the *query* was too narrow or slightly off-vocabulary —
not that the catalog lacks a relevant kit. The agent should broaden
(`broaden=True`) and retry with **adjacent supported traits** (e.g. add
`api-design` alongside `rest-api`, or `oidc` alongside `auth`) before
concluding nothing fits. Giving up after one weak query is the failure mode we
are designing against.

### 4. Bootstrap guidance is separate from full kit content — on purpose

The bootstrap routine teaches the agent *how to drive Quartermaster*. Kit
content teaches it *how to implement a capability*. Keeping them separate means
the agent pays a tiny, fixed token cost to query well, and only loads heavy kit
content once a kit is actually selected. Fetch the routine with `get_prompt`;
fetch implementation guidance with `get_kit` (preferably section-scoped).

### 5. How this supports token-efficient discovery

The whole point is to spend few tokens finding the right kit:

- a one-line invariant in the MCP description steers the first query,
- the bootstrap prompt is a short, structured checklist fetched only when
  needed,
- `get_kit_outline` and section-scoped `get_kit` defer the largest payload
  (full kit text) until the agent is implementing that specific aspect.

Querying with normalized, in-vocabulary traits gets a strong match on the first
or second call instead of a scattershot series of weak ones.

## Recommended `AGENTS.md` block

You have two options. **Prefer the minimal block** — it is light-touch and
survives Quartermaster's evolution. Reach for the explicit version only when a
team wants the steps spelled out in-repo.

### Minimal (recommended)

Add this single line to a Quartermaster-backed repository's `AGENTS.md` /
`CLAUDE.md`:

```md
When quartermaster is available, treat its published trait vocabulary and
bootstrap guidance as the source of truth for kit discovery; normalize user
intent to supported traits before selection and retry when coverage is low.
```

That sentence is the whole contract. It names **concepts**, not tool, prompt,
or endpoint names, so it stays correct even if Quartermaster renames tools or
moves where bootstrap guidance is delivered. Why each phrase is there:

- **"When quartermaster is available"** — conditional, so the repo stays usable
  when the server is not connected; nothing here hard-depends on it.
- **"published trait vocabulary … as the source of truth"** — use the traits
  Quartermaster *publishes* (`list_available_traits`) instead of inventing
  labels; made-up names like `auth` or `internal-service` will not match the
  catalog's `requires`/`excludes` rules.
- **"bootstrap guidance … as the source of truth"** — Quartermaster already
  ships the discovery routine (its MCP `instructions` plus the
  `trait_selection_bootstrap` prompt); the repo defers to it rather than
  restating it, so the workflow can change server-side without editing the repo.
- **"normalize user intent to supported traits before selection"** — translate
  natural-language requests into catalog trait labels *before* calling
  `select_kits`, not after.
- **"retry when coverage is low"** — one weak query is not a dead end; re-map to
  a better trait set (or `broaden=True`) and try again before declaring a gap.

### Explicit (optional, spelled out)

When a team prefers the steps in-repo, this expanded block says the same thing
with the tool names made concrete:

```md
## Selecting instruction kits from Quartermaster

This project uses the Quartermaster MCP to load instruction kits **per task**,
not as a fixed list. When a task may touch architecture, tooling, or a new
capability:

1. Treat Quartermaster's advertised trait vocabulary as the source of truth —
   call `list_available_traits` and map the request onto supported
   `languages`, `frameworks`, `capabilities`, and `contexts`.
2. Normalize free-form wording to that vocabulary before selecting (e.g.
   "REST API on k8s with login" → framework `fastapi`, capabilities
   `rest-api`/`auth`, context `deploy`).
3. Call `select_kits` with the normalized traits; if coverage is low or
   `broadening_recommended` is set, broaden and retry with adjacent supported
   traits before deciding no kit applies.
4. For the exact routine, fetch Quartermaster's trait-selection bootstrap
   prompt (`list_prompts` → `get_prompt`) instead of duplicating it here.
5. Prefer `get_kit_outline` and section-scoped `get_kit` over loading full
   kits up front.
```

What each line of the explicit block is trying to achieve:

- **"…load instruction kits per task, not as a fixed list."** Stops the agent
  pinning a stale kit list that loads too much or too little; traits often only
  emerge mid-conversation.
- **Step 1 (source of truth).** Anchors every query to the advertised
  vocabulary so the agent stops inventing traits like `internal-service`.
- **Step 2 (normalize).** Converts the user's natural language into trait
  values that can actually match, which is where most weak queries are lost.
- **Step 3 (broaden and retry).** Turns a low-coverage result into a second
  attempt rather than a premature "no kit applies".
- **Step 4 (fetch the prompt).** Keeps the authoritative routine in
  Quartermaster — one source, free to evolve — instead of a copy that rots in
  every repo. It also references the registry generically, not a single
  hard-coded prompt name.
- **Step 5 (outline first).** Defers the largest token cost until the agent
  is implementing that specific kit.
