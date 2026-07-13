# See what Quartermaster did

Kit discovery is meant to be invisible, but sometimes you want to check what
happened for a task: which kits were chosen, which traits the task resolved to,
and how the match was made. Everything here comes back from the same tools your
agent already uses — no special access.

## Which kits and traits a task resolved to

Every `resolve_kits` response already reports how it decided:

- **`engine`** — how the task was mapped to traits: `llm` (a language model),
  `embedding` (local semantic matching), or `lexical` (the always-on keyword
  floor). A drop to `lexical` means the richer engines were unavailable and
  matching was coarser.
- **`inferred_traits`** and their **`provenance`** — the traits the task was
  read as, and where each came from.
- **`kits`** — the ranked recommendations, each with a `score` and the reasons
  it matched.

Ask your agent to run `resolve_kits` for the task and show you those fields.

## Full diagnostics

For the complete picture, request diagnostics explicitly:

```text
resolve_kits(task="<describe your task>", include_diagnostics=true)
```

This adds a `_diagnostics` block with the inference engine, per-trait
provenance, per-kit scores, trait coverage, and whether a clarification round
ran — the evidence behind the recommendation.

## Your personalization memory

If the operator has enabled per-user memory, Quartermaster keeps a small,
familiarity-based profile from your own past resolves and uses it as a gentle
tie-breaker (it never overrides a genuine trait match). You control it:

- **`get_my_memory`** — view the profile Quartermaster holds for you.
- **`reset_my_memory`** — clear it and start fresh.

If those tools are not offered, the feature is switched off on your instance.

## Instance-wide metrics

The above is scoped to a single task or to you. Aggregate usage across the
whole instance — which kits earn their place, how much content is delivered,
selection health — is an operator concern; see
[Observability](../operator/observability.md).
