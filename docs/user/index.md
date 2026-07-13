# Users

Guides for people who use a running Quartermaster instance — one your team
already hosts, or the published container an operator has deployed. You do not
need the source code or a local build to follow anything here.

There are two kinds of user:

## MCP users

You point a coding agent at Quartermaster and let it load instruction kits for
you, per task. Most of the time this is invisible — the agent discovers and
loads the right kits on its own.

- **[Connect your agent](connecting-an-agent.md)** — point a coding agent at a
  Quartermaster instance over MCP.
- **[Downstream agent guidance](downstream-agent-guidance.md)** — the short
  `AGENTS.md` briefing to add to a Quartermaster-backed repo so agents discover
  kits reliably.
- **[Per-repo kit pinning (`.quartermaster.toml`)](quartermaster-toml.md)** —
  remember which kit version a repository follows.
- **[See what Quartermaster did](diagnostics.md)** — inspect which kits and
  traits a task resolved to, and the per-user memory it keeps for you.

## Kit authors

You create, edit, and curate the kits Quartermaster serves.

- **[Authoring kits](authoring-kits.md)** — how a kit is structured, and how to
  write one against a running instance.
- **[Evaluating kits](evaluating-kits.md)** — measure how well a catalog
  resolves: coverage, false-exclusions, cross-kit interference, and the impact
  of a change.

```{toctree}
:hidden:
:maxdepth: 1

connecting-an-agent
downstream-agent-guidance
quartermaster-toml
diagnostics
authoring-kits
evaluating-kits
```
