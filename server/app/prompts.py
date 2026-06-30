"""Canned prompt templates exposed through MCP tools."""

from __future__ import annotations

_PROMPTS: list[dict[str, str]] = [
    {
        "name": "greet",
        "title": "Meet Quartermaster",
        "intent": (
            "Introduce Quartermaster to a coding agent connecting for the "
            "first time: what it is, how to load kits, and where to go next."
        ),
        "prompt_template": (
            "You are connected to **Quartermaster**, a self-hosted MCP server "
            "that serves versioned AI *instruction kits* on demand.\n\n"
            "What it is: kits are agent-facing guidance for specific "
            "architecture, tooling, and capability choices (for example local "
            "auth, OIDC, a FastAPI + Vuetify stack). Kits are loaded as extra "
            "context per task and are never copied into the target project, so "
            "the repo stays clean and you always get the latest guidance. Load "
            "kits per task, not once per project — the traits a task touches "
            "often only emerge mid-conversation.\n\n"
            "How to load kits:\n"
            "1. Fast path (start here): call `resolve_kits(task=\"…\")` with a "
            "plain-language description of the work. It maps the task to "
            "traits, ranks the matching kits, and returns the recommendation "
            "with each kit's `always_load` sections already inlined. Pull "
            "anything listed under `fetch_on_demand` with "
            "`get_kit(name, sections=[…])` when you reach that aspect.\n"
            "2. Manual path (finer control): `list_available_traits` -> "
            "`select_kits` -> `get_kit_outline` -> `get_kit(sections=[…])` "
            "when you have already mapped the task to explicit traits or want "
            "ranking diagnostics.\n\n"
            "Discover more: call `list_prompts` to see the guided workflows "
            "available (bootstrapping, legacy assessment, tech-debt "
            "modernization, and more).\n\n"
            "Integrate Quartermaster into this project: call "
            "`get_prompt('integrate_project')` and follow the returned steps "
            "to wire it into the project's agent-instruction files."
        ),
    },
    {
        "name": "integrate_project",
        "title": "Integrate Quartermaster Into This Project",
        "intent": (
            "Wire Quartermaster into the host project's agent-instruction "
            "files so future agents know to use it for kit discovery."
        ),
        "prompt_template": (
            "Integrate Quartermaster into this project's agent instructions. "
            "Follow these steps:\n\n"
            "1. Scan the project root for any of these agent-instruction files "
            "(more than one may exist): `CLAUDE.md`, `AGENTS.md`, "
            "`.cursorrules`, `.windsurfrules`, "
            "`.github/copilot-instructions.md`, `GEMINI.md`.\n"
            "2. For each file found, add the following paragraph near the top "
            "(after any existing preamble), under a `## Quartermaster` heading "
            "if the file uses headings:\n\n"
            "   > When Quartermaster is available, treat its published trait "
            "vocabulary and bootstrap guidance as the source of truth for kit "
            "discovery; normalize user intent to supported traits before "
            "selection and retry when coverage is low.\n\n"
            "3. If no matching file is found, offer the user a multiple-choice "
            "selection of the typical options — `CLAUDE.md`, `AGENTS.md`, "
            "`.cursorrules`, `.windsurfrules`, "
            "`.github/copilot-instructions.md`, `GEMINI.md` — and create "
            "whichever the user picks.\n"
            "4. Do not duplicate the paragraph if it is already present.\n"
            "5. After writing, confirm to the user which file(s) were modified "
            "and that Quartermaster is now wired in.\n\n"
            "The paragraph is intentionally minimal — it tells future agents "
            "to use Quartermaster without hard-coding a kit list. Do not "
            "expand or paraphrase it."
        ),
    },
    {
        "name": "trait_selection_bootstrap",
        "title": "Quartermaster Trait-Selection Bootstrap",
        "intent": (
            "How to drive Quartermaster's own trait-selection workflow "
            "efficiently and correctly. This is guidance for *using* "
            "Quartermaster to find kits — not implementation work on the "
            "target project."
        ),
        "prompt_template": (
            "Use this routine when selecting Quartermaster kits for a task:\n"
            "1. Default to the one-shot `resolve_kits` tool: pass a "
            "plain-language task description and it maps the task to traits, "
            "ranks kits, and returns the recommendation with each kit's "
            "`always_load` sections inlined. Pull anything it lists under "
            "`fetch_on_demand` with section-scoped `get_kit`. Use the manual "
            "steps below only for finer control (traits already known, "
            "ranking diagnostics, or incremental multi-kit loading).\n"
            "2. Treat Quartermaster's advertised trait vocabulary as "
            "authoritative — only supported `languages`, `frameworks`, "
            "`capabilities`, and `contexts` match; invented trait names do "
            "not. (`resolve_kits` applies this for you.)\n"
            "3. Normalize the user's wording to that vocabulary before "
            'selecting (e.g. "REST API" -> framework `fastapi` + capability '
            '`rest-api`; "k8s"/"deploy target" -> context `deploy`; '
            '"logging" -> `observability`/`correlation-id`; "audit" -> '
            "`security`).\n"
            "4. Call `list_available_traits` whenever the request introduces "
            "a new runtime, deployment, or capability concern you have not "
            "already mapped.\n"
            "5. Call `select_kits` with the normalized traits.\n"
            "6. If coverage is low or `broadening_recommended` is set, "
            "broaden and retry with adjacent supported traits before "
            "concluding that no relevant kit exists.\n"
            "7. Prefer prompt and outline discovery "
            "(`list_prompts`/`get_prompt`, `get_kit_outline`, "
            "section-scoped `get_kit`) over loading full kit content."
        ),
    },
    {
        "name": "legacy_assessment",
        "title": "Legacy Project Diagnostic",
        "intent": (
            "Assess an aging codebase and identify high-value "
            "applicable kits."
        ),
        "prompt_template": (
            "Analyze this legacy project and infer traits from the "
            "repository. "
            "Use the instruction MCP to select candidate kits, broaden "
            "if needed, "
            "and explain top recommendations with migration risk."
        ),
    },
    {
        "name": "bootstrap_sequence",
        "title": "Project Bootstrap Kit Sequence",
        "intent": "Build a staged kit loading sequence for a project setup.",
        "prompt_template": (
            "Given this project context, infer stack traits and produce "
            "a recommended "
            "kit sequence with dependencies, ordering, and rationale."
        ),
    },
    {
        "name": "capability_extension",
        "title": "Add Capability To Existing Project",
        "intent": (
            "Add a new capability while preserving compatibility with "
            "current stack."
        ),
        "prompt_template": (
            "Identify what is missing for the target capability, select "
            "relevant kits, "
            "flag conflicts with existing traits, and propose an "
            "implementation plan."
        ),
    },
    {
        "name": "tech_debt_modernization",
        "title": "Tech Debt Modernization Priority",
        "intent": (
            "Prioritize modernization work with kit-guided adoption "
            "steps."
        ),
        "prompt_template": (
            "Assess technical debt hotspots, map them to applicable "
            "kits, and rank "
            "changes by impact, effort, and rollout risk."
        ),
    },
]


def list_canned_prompts() -> list[dict[str, str]]:
    """Return all canned prompt definitions."""
    return list(_PROMPTS)


def get_canned_prompt(name: str) -> dict[str, str]:
    """
    Return a canned prompt by name.

    :raises KeyError: If *name* does not match a canned prompt.
    """
    for prompt in _PROMPTS:
        if prompt["name"] == name:
            return dict(prompt)
    raise KeyError(name)
