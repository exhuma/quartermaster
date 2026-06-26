# Recommended `AGENTS.md` block

If you want coding agents to use Quartermaster well in **your own**
repositories, add one short instruction to that repository's `AGENTS.md`
(or `CLAUDE.md`). This page explains the recommended block, why it exists,
and how it makes agents more reliable.

## The block

```md
When quartermaster is available, treat its published trait vocabulary and
bootstrap guidance as the source of truth for kit discovery; normalize user
intent to supported traits before selection and retry when coverage is low.
```

That single sentence is the whole contract. Everything below is rationale —
you do **not** need to copy it into your repository.

## Why each phrase is there

- **"When quartermaster is available"** — the guidance is conditional. The
  repository stays usable when Quartermaster is not connected; nothing here
  hard-depends on the server being present.
- **"published trait vocabulary … as the source of truth"** — the agent should
  use the traits Quartermaster *publishes* (`list_available_traits`) instead of
  inventing its own labels. Made-up trait names like `auth` or `react-stuff`
  will not match the catalog's `requires`/`excludes` rules and lead to poor
  selection.
- **"bootstrap guidance … as the source of truth"** — Quartermaster already
  ships the discovery workflow (its MCP `instructions`, surfaced to clients on
  connect). The repository defers to that guidance instead of restating it, so
  the workflow can change server-side without touching every repository.
- **"normalize user intent to supported traits before selection"** — the agent
  should translate natural-language requests into the catalog's trait labels
  *before* calling `select_kits`, rather than querying with raw user phrasing.
- **"retry when coverage is low"** — one weak query is not a dead end. If
  selection returns little or flags that broadening is recommended, the agent
  should re-map the task to a better trait set (or broaden) and try again
  before giving up.

## How it helps trait normalization

Coding agents tend to coin their own vocabulary ("add login", "make it
reactive"). Those phrases do not line up with the catalog's trait categories
(languages / frameworks / capabilities / contexts), so naïve selection
under- or mis-matches kits.

The block fixes the direction of authority: the **published** trait list is
canonical, and the agent's job is to map intent onto it. In practice that means
calling `list_available_traits` first and choosing from what it returns —
turning "add login" into a supported capability trait instead of a guessed
label. Better-mapped traits feed the `requires`/`excludes`/`priority` scoring,
which produces better kit matches.

## How it helps agents retry intelligently

Trait selection can return thin results for two very different reasons: the
catalog genuinely lacks coverage, or the agent simply mapped the task to the
wrong traits. "Retry when coverage is low" tells the agent to assume the second
case first.

So instead of stopping after a single weak query, the agent re-examines the
task, picks a better-mapped trait set (or sets `broaden=True` when
`broadening_recommended` is flagged), and selects again. Only after that should
it conclude there is a real gap — at which point the gap-reporting tools
(`check_existing_gap_issue` / `request_clarification_or_addition`) are the right
next step.

## Why it is intentionally light-touch

The block names **concepts**, not endpoints. It deliberately avoids tool names,
prompt names, URLs, or a fixed kit list. That keeps it future-friendly:

- **No over-specifying internals.** Quartermaster can rename tools, change
  prompt names, or move where bootstrap guidance is delivered, and the block
  stays correct because it points at "published … vocabulary and bootstrap
  guidance" rather than any specific mechanism.
- **No hard-coded kit list.** Kits are meant to be chosen **per task**, since
  the traits a task touches often only emerge mid-conversation. A static list
  in `AGENTS.md` would load too much or too little; the block nudges discovery
  instead. (See [README → How agents should use it](README.md#how-agents-should-use-it).)
- **Authoritative, not duplicated.** The detailed discovery workflow lives in
  one place — Quartermaster's own `instructions` — and the block defers to it,
  so repositories never drift out of sync with the server.
