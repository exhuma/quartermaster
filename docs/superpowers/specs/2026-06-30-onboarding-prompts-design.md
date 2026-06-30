# Design: Onboarding Prompts + Diagnostic Mode

**Date:** 2026-06-30  
**Status:** Draft (rebased onto `b6705a7` — MCP prompts/sampling/elicitation)

## Context

Quartermaster lacks onboarding guidance for agents connecting to it for the first time, and no self-service mechanism for a user who wants to integrate it into their project. Additionally, there is no way to evaluate whether QM's kit guidance actually influences agent behaviour — which is blocking adoption evaluation.

Three additions address this:
1. A `greet` prompt that orients a newly-connected agent.
2. An `integrate_project` prompt that instructs a coding agent to wire QM into the host project's instruction files.
3. An `include_diagnostics` flag on `resolve_kits` that causes the response to embed a directive for the agent to produce a human-readable impact report after the task is complete.

### Alignment with the rebased main (`b6705a7`)

Main now registers MCP primitives properly, which *simplifies* this design:

- **Prompts are dual-surfaced automatically.** `app/prompts.py` `_PROMPTS` is the single source of truth. `_register_canned_prompts()` (`main.py:267`) iterates it and registers every entry as a native `@mcp.prompt` (user-selectable slash command / prompt-gallery item) *while* the same entries stay available to autonomous agents via the `list_prompts`/`get_prompt` tools. **Adding `greet` and `integrate_project` to `_PROMPTS` therefore lands on both surfaces with no main.py change** — `greet` surfacing as a client slash command is exactly what onboarding wants.
- **`resolve_kits` is now `async` with an injected `Context`** (`main.py:546`), and infers traits via MCP **sampling** (the client's own LLM) ahead of the LLM→embeddings→lexical chain, plus a one-round **elicitation** clarification on empty/low-confidence tasks. The returned `result` dict already carries `engine` (now also `"sampling"`), `inferred_traits.provenance`, `confidence`, `coverage`, and per-kit `score`/`confidence`/`reasons` — so the diagnostics block is assembled in `main.py` from `result` and **`resolver.py` needs no change**.

---

## Prompt 1: `greet`

**Intent:** Orient a coding agent that has just connected to Quartermaster.

**Trigger context:** The agent (or user, via the agent) asks "what is this?", "how do I use Quartermaster?", or similar.

**Content (four parts):**

1. **Purpose** — QM is a self-hosted MCP server that serves versioned AI instruction kits on demand, per task. Kits are never copied into the target project; they are loaded as context and discarded when the task is done. This keeps the target repo clean and ensures agents always get the latest guidance.

2. **Tool chain** — Two paths:
   - Fast path: `resolve_kits(task="…")` — one call; maps the task to traits, ranks kits, returns the top recommendations with `always_load` sections inlined. Use `get_kit(name, sections=[…])` to fetch any `fetch_on_demand` sections.
   - Manual path (when you already know the traits or need diagnostics): `list_available_traits` → `select_kits` → `get_kit_outline` → `get_kit(sections=[…])`.

3. **`list_prompts` pointer** — Call `list_prompts()` to see the available guided workflows (bootstrapping, legacy assessment, tech debt, etc.).

4. **Integration hint** — To wire Quartermaster into this project's agent instructions, call `get_prompt('integrate_project')` and follow the returned steps.

---

## Prompt 2: `integrate_project`

**Intent:** Instruct a coding agent to add the minimal QM integration paragraph to the host project's instruction files.

**Trigger context:** The user says "integrate Quartermaster", "add Quartermaster to my project", "connect QM", or similar.

**Content (step-by-step directive for the coding agent):**

1. Scan the project root for any of the following files (more than one may exist): `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`, `GEMINI.md`.

2. For **each file found**, add the following paragraph near the top (after any existing preamble), under a heading such as `## Quartermaster` if appropriate:

   > When Quartermaster is available, treat its published trait vocabulary and bootstrap guidance as the source of truth for kit discovery; normalize user intent to supported traits before selection and retry when coverage is low.

3. If **no matching file is found**, offer the user a multiple-choice selection of the typical options — `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, `.windsurfrules`, `.github/copilot-instructions.md`, `GEMINI.md` — and create whichever the user picks.

4. Do not duplicate the paragraph if it is already present.

5. After writing, confirm to the user which file(s) were modified and that QM is now wired in.

**Note for the agent:** The paragraph is intentionally minimal — it tells future agents to use QM without hard-coding a kit list. Do not expand or paraphrase it.

---

## Diagnostic mode: `include_diagnostics` on `resolve_kits`

### Motivation

During evaluation, the user needs to know not just which kits were selected, but whether and how the kit guidance actually shaped implementation decisions. A raw metrics dump is not sufficient; the agent must produce a human-readable causal report.

### Mechanism

Add `include_diagnostics: bool = False` to the now-`async` `resolve_kits` tool. Place it before the injected `ctx: Context | None = None` parameter so `ctx` stays last:

```python
async def resolve_kits(
    task: str,
    broaden: bool = False,
    limit: int = 8,
    max_sections_per_kit: int = 8,
    include_diagnostics: bool = False,
    ctx: Context | None = None,
) -> dict:
```

When `True`, the response gains a `_diagnostics` key (underscore prefix marks it as metadata, not kit content), assembled in `main.py` from the `result` dict that `resolve_kits` already holds (after any elicitation re-resolve):

```jsonc
"_diagnostics": {
  "engine": "sampling",               // inference engine that won: sampling | llm | embedding | lexical
  "clarification_used": false,         // true if elicitation asked the user to refine the task
  "trait_provenance": [               // per-trait origin (from result.inferred_traits.provenance)
    {"category": "capabilities", "value": "authentication", "source": "sampling"},
    ...
  ],
  "kit_scores": [                     // per-kit scoring detail (from result.kits)
    {
      "name": "module-auth-oidc",
      "score": 92,
      "confidence": "high",
      "reasons": ["match:capabilities", "require-ok:contexts"]
    },
    ...
  ],
  "coverage": 0.87,                   // fraction of inferred traits matched
  "selection_confidence": "high",
  "report_instruction": "..."         // see below
}
```

`clarification_used` is tracked by `resolve_kits` itself (it already knows whether the low-confidence elicitation branch ran) — this is new evaluation signal the rebased main makes available, and it matters for judging whether QM needed hand-holding to land the right kits.

### Report instruction (embedded in `_diagnostics.report_instruction`)

The string tells the agent what to do *after* it finishes the task:

> Quartermaster diagnostics are active. After completing this task, present the user with a **Quartermaster Insights report** containing the following sections:
>
> **1. Traits inferred** — list the languages, frameworks, capabilities, and contexts that were detected from the task description, and note which inference engine (sampling / LLM / embedding / lexical) identified them. Mention if you were asked to clarify the task before kits could be matched.
>
> **2. Kits selected** — for each kit loaded, name it and summarise the key guidance it provided (invariants, required patterns, prohibited approaches).
>
> **3. Impact on this task** — for each significant implementation decision, state whether and how a kit's guidance shaped it. Be explicit: e.g. "Used PKCE flow because module-auth-oidc requires it" or "Structured JWT middleware per module-fastapi invariant". If a decision was *not* influenced by any kit, say so — gaps in coverage are useful data for evaluating Quartermaster.
>
> Keep the report concise but honest. Its purpose is to let the user assess whether Quartermaster's guidance improved the outcome.

### Implementation sketch

- `server/app/main.py`: add `include_diagnostics` to `resolve_kits`. After the result is finalised (post-elicitation), when the flag is set, build the `_diagnostics` dict from `result` (`engine`, `inferred_traits.provenance`, per-kit `score`/`confidence`/`reasons`, `coverage`, `confidence`) plus the locally-tracked `clarification_used`, attach the report-instruction string, and add it under `result["_diagnostics"]`. ~20 lines, isolated in a small `_build_diagnostics(result, *, clarification_used)` helper.
- `resolver.py`, `kits.py`, and the scoring model are **unchanged** — all needed data is already in the returned `result`.

---

## Files to change

| File | Change |
|---|---|
| `server/app/prompts.py` | Add `greet` and `integrate_project` entries to `_PROMPTS` (auto-registered as native prompts + tools by the existing `_register_canned_prompts()`) |
| `server/app/main.py` | Add `include_diagnostics` to `resolve_kits`; add `_build_diagnostics()` helper; attach `_diagnostics` to the result when the flag is set, tracking `clarification_used` |
| `server/tests/test_native_prompts.py` | Extend to assert `greet` and `integrate_project` are registered as native prompts and render their text |
| `server/tests/test_resolve_kits_tool.py` | Verify `include_diagnostics=True` adds `_diagnostics` (engine, trait_provenance, kit_scores, coverage, report_instruction, clarification_used) and that the default keeps the response unchanged |

(`server/app/resolver.py` and `server/app/kits.py` are intentionally untouched.)

---

## Verification

1. `uv run pytest` — all existing tests must pass; new/extended tests cover the two prompts and the diagnostics block (`test_native_prompts.py`, `test_resolve_kits_tool.py`).
2. Manual spot-check: call `get_prompt('greet')` and `get_prompt('integrate_project')` via an MCP client (and confirm both appear as native prompts / slash commands) and that the content reads naturally.
3. Call `resolve_kits(task="implement JWT authentication", include_diagnostics=True)` and confirm the response contains `_diagnostics` with `engine`, `clarification_used`, `trait_provenance`, `kit_scores`, `coverage`, and `report_instruction`.
4. Confirm that without `include_diagnostics` the response is byte-for-byte the current output (no `_diagnostics` key present).
