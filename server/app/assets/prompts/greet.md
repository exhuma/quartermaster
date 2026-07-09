You are connected to **Quartermaster**, a self-hosted MCP server that serves versioned AI *instruction kits* on demand.

What it is: kits are agent-facing guidance for specific architecture, tooling, and capability choices (for example local auth, OIDC, a FastAPI + Vuetify stack). Kits are loaded as extra context per task and are never copied into the target project, so the repo stays clean and you always get the latest guidance. Load kits per task, not once per project — the traits a task touches often only emerge mid-conversation.

How to load kits:
1. Fast path (start here): Call `resolve_kits(task="…")` on any edit/plan task (including subsequent user prompts requesting changes, or internally-driven agent edit loops). It maps the task to traits, ranks kits, and inlines `always_load` sections. Pull on-demand sections with `get_kit(name, sections=[…])` only once per session to save context, unless previous sections were compacted away from your context.
2. Manual path (finer control): `list_available_traits` -> `select_kits` -> `get_kit_outline` -> `get_kit(sections=[…])` when you have already mapped the task to explicit traits or want ranking diagnostics.

Discover more: call `list_prompts` to see the guided workflows available (bootstrapping, legacy assessment, tech-debt modernization, and more).

Integrate Quartermaster into this project: call `get_prompt('integrate_project')` and follow the returned steps to wire it into the project's agent-instruction files.
