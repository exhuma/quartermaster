This MCP serves versioned AI *instruction kits* — agent-facing guidance for
specific architecture, tooling, and capability choices (for example: local
auth, OIDC, a FastAPI + Vuetify stack). Kits are loaded on demand as extra
context; their files are never copied into the target project.

**Use kits per task, not once per project.** Avoid hard-coding a fixed kit
list in CLAUDE.md / AGENTS.md — a fixed list loads too much or too little. The
traits a task touches often only emerge during the conversation: a request to
"add authentication" may resolve to OIDC after some discussion, bringing OIDC
kits into scope that were irrelevant before. A static list cannot react to
that.

**Default path — call `resolve_kits` on any edit or plan.** Run this on the
initial user-prompt, whenever any subsequent user-prompt requests to make or
plan changes, and whenever you need to make changes during an internally-driven
agentic loop. Pass a plain-language description of the work
(`resolve_kits(task="…")`). The server maps the task onto its trait vocabulary,
ranks the matching kits, and returns the recommendation with each kit's
`always_load` sections already inlined — collapsing the whole discovery
sequence into one call and keeping it out of your context. Re-run it whenever
the task's direction shifts or new traits come into scope.

**Re-run triggers — this is a standing behavior, not one-time setup.** Call
`resolve_kits` again whenever any of these occur, even mid-session:
- the user asks you to make or plan a change;
- you begin a new subsystem, feature, or aspect of the work;
- the task's direction shifts or new traits come into scope (e.g. "add login"
  becoming OIDC);
- you resume editing after a context compaction/summarization (re-resolve
  before your next edit).
Left to model discretion this behavior *decays over a long session*: agents
reliably resolve at the start and drift off it later. It stays reliable only
when the client harness enforces it. If you operate a Quartermaster
integration, wire that enforcement — see the **Integrate** page in the
Quartermaster web UI for copy-pasteable Claude Code hooks and equivalents for
other agents.

**Load lean and handle session state.** Pull any extra sections listed under
`fetch_on_demand` with `get_kit(name, sections=[…])` when you reach that aspect.
To preserve token space, deliver each required section's contents only once per
session/conversation. Offering optional sections can be done multiple times
(sparingly) as it does not consume much context. Note that because this server
cannot know whether an already delivered section was "compacted away" by any
context-compression actions, you may re-fetch and re-deliver a section if you
deem it appropriate when you see a new request or reach that aspect.

Use the manual loop below only when you need finer control: you have already
mapped the task to explicit traits, you want to inspect ranking diagnostics,
or you are loading several kits incrementally.

1. **Discover coverage** — call `list_available_traits` for the trait
   vocabulary (languages, frameworks, capabilities, contexts) and `list_kits`
   for the available kits.
2. **Map the task to traits** — this server's advertised vocabulary is
   authoritative, so normalize the developer's wording onto supported
   `languages`/`frameworks`/`capabilities`/`contexts` instead of inventing
   trait names; infer which traits the task touches from the repository and
   intent, and revisit as the direction firms up. (`resolve_kits` does this
   step for you.)
3. **Load matching guidance** — call `select_kits` with the task's traits (use
   `broaden=True` if `broadening_recommended` is set, and retry with adjacent
   supported traits when coverage stays low — before concluding no kit
   applies), narrow with `explain_kit_candidate`, then load each chosen kit.
   Re-run this when new traits come into scope mid-task.
4. **Load lean** — call `get_kit_outline` to see a kit's sections, then
   `get_kit` with `sections=[…]` to pull only the sections the current step
   needs (start with the ones flagged `always_load`). Read a kit's full text
   (omit `sections`) only when you're implementing all of it. For tasks that
   touch several kits, load each kit's content when you reach that aspect, not
   all up front.

For a compact, operational version of this trait-selection routine, fetch the
bootstrap prompt from the prompt registry (`list_prompts` → `get_prompt`).

**Version pinning — remember which kit major a repo follows.** When a kit ships
a breaking change it gains a new major (`v2`), and both versions coexist. So a
repo keeps applying consistent conventions, record its per-kit major in a
repo-side `.quartermaster.toml` file (the server is stateless about this and
never writes to your repo — you do, with your own file tools). At task start,
read that file and pass what you find: `resolve_kits(task="…", pins={…},
project_id="…")`, or `get_kit_outline(name, pin="…")` / `get_kit(name,
pin="…")`. When a kit has multiple majors and you pass no pin, the server
serves the **earliest** major and attaches a `version_advisory` describing the
newer version's breaking changes — surface it, ask the user whether to stay or
upgrade, then write the chosen major back to `.quartermaster.toml`. A pin only
constrains a kit's *version*, never which kits are selected, so it stays
compatible with per-task `resolve_kits`. Fetch the `quartermaster_pin_file`
prompt (`list_prompts` → `get_prompt`) for the canonical schema and workflow.
