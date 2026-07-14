# `.quartermaster.toml` — repo-side kit version pins

Quartermaster serves **versioned** instruction kits. When a kit ships a breaking
change it gains a new major (`v2`) and both versions coexist in the catalog. To
keep applying consistent conventions, a repository records which major of each
kit it follows in a small `.quartermaster.toml` file in its root.

This is the **only** place that state lives. The Quartermaster server is stateless
about pins — it never stores per-project state and never writes to your repo. The
coding **agent** reads and writes this file with its own file tools; the server
only serves versions and, when asked without a pin, returns an *advisory* so the
agent can prompt the user and record their choice.

## Why repo-side (not server-side)

The server is blind to your repo — it only sees what the agent passes it. A
server-side pin would need a project key on every call, and that key could only
come from something in the repo anyway (a fragile git remote, or a file). Putting
the pin directly in the file needs no identity at all: the file *is* the state,
colocated with the code and portable across forks and remote moves.

A version pin is **not** the
["don't hard-code a kit list in `AGENTS.md`"](downstream-agent-guidance.md)
anti-pattern. A pin does not select kits; it only constrains which *version* a
selected kit resolves to. It stays fully compatible with per-task `resolve_kits`.

## Schema

```toml
# .quartermaster.toml — which major version of each kit this repo follows.
# Managed by your coding agent via Quartermaster. The server never writes this.
schema = 1

# Optional, generated once and then left alone. A stable label used only for
# Quartermaster's version-adoption telemetry — NOT a lookup key, so losing it
# costs only a grouping label, never a pin.
project_id = "qm_<random>"

[kits]
# Only kits with more than one major need an entry. Single-version kits: nothing.
module-auth-oidc = "v2"
```

`schema`
: File-format version (currently `1`).

`project_id`
: Optional stable telemetry label; generated once, never regenerated.

`[kits]`
: Per-kit major pin, `<kit-name> = "v<N>"`.

## How agents use it

1. **At task start**, read `.quartermaster.toml` and collect its `[kits]` map.
2. **Pass it to the tools**: `resolve_kits(task="…", pins={…}, project_id="…")`,
   or `get_kit_outline(name, pin="…")` / `get_kit(name, pin="…")`.
3. **On a `version_advisory`** (returned when a multi-version kit is requested
   without a pin — the server conservatively serves the earliest major), surface
   the breaking changes, ask the user whether to stay or upgrade, then write the
   chosen major back to `[kits]`. This makes the decision a one-time cost.

The server ships this workflow in its MCP `instructions` and as the
`quartermaster_pin_file` prompt (`list_prompts` → `get_prompt`).

## Operator controls (optional)

The pin stays authoritative in the repo, but an operator can layer two things on
top without owning the pins:

- **Adoption telemetry** — agents report the served version (and `project_id`),
  recorded in the local metrics store and surfaced as a per-kit adoption chart on
  the kit page. Gate with `QM_VERSION_TELEMETRY_ENABLED`.
- **Version policy** — a `QM_VERSION_POLICY_FILE` (TOML) declares per-kit
  `min_version` / `deprecated` majors, surfaced in the advisory for the agent to
  enforce:

  ```toml
  [kits.module-auth-oidc]
  min_version = "v2"
  deprecated = ["v1"]
  ```

Set `QM_CONSERVATIVE_DEFAULT_ENABLED=false` to revert unpinned multi-version kits
to latest-wins instead of the earliest-major default.
