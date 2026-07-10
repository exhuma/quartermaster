Remember which major version of each Quartermaster kit this repository follows,
so future agents keep applying consistent conventions instead of silently
jumping to a new major when a kit ships a breaking change.

Quartermaster is stateless about this: the server never writes to your repo and
never stores per-project state. The pin lives in a small `.quartermaster.toml`
file in the repo root, which YOU (the coding agent) read and write with your own
file tools.

## File schema

```toml
# .quartermaster.toml — which major version of each kit this repo follows.
# Managed by your coding agent via Quartermaster. The server never writes this.
schema = 1

# Optional, generated once and then left alone. A stable label used only for
# Quartermaster's version-adoption telemetry — it is NOT a lookup key, so
# losing it costs only a grouping label, never a pin.
project_id = "qm_<random>"

[kits]
# Only kits that have shipped a breaking change (more than one major) need an
# entry. A single-version kit needs nothing here.
module-auth-oidc = "v2"
```

## Workflow

1. **At task start**, read `.quartermaster.toml` if it exists. Collect its
   `[kits]` table into a pins map and note its `project_id`.
2. **Pass what you read** to the tools:
   - `resolve_kits(task="…", pins={…}, project_id="…")`
   - `get_kit_outline(name, pin="v2")` / `get_kit(name, pin="v2", project_id="…")`
   A pinned kit is served at that major with no advisory.
3. **Handle a `version_advisory`.** When a kit has more than one major and you
   passed no pin, Quartermaster serves the **earliest** major (an unpinned repo
   predates the split) and attaches a `version_advisory` listing the newer
   version's breaking changes. Surface it to the user:
   - present `breaking_changes` (and heed `user_facing_warning`);
   - ask whether to stay on `served_version` or upgrade to `latest_version`;
   - on their decision, **write the pin** back to `.quartermaster.toml`
     (`[kits].<name> = "<chosen major>"`). This makes the choice a one-time
     cost — subsequent resolves are deterministic.
4. **Generate `project_id` once** if it is absent and you are creating or
   updating the file: a short opaque string (e.g. `qm_` + a random token).
   Never regenerate it if it already exists.

## Rules

- A version pin is not a hard-coded kit *list* — it does not select kits, it
  only constrains which version a selected kit resolves to. It is fully
  compatible with per-task `resolve_kits`.
- Keep entries only for kits that actually have multiple majors; prune stale
  entries for kits that were removed.
- If a pin references a version that no longer exists, Quartermaster falls back
  to the conservative default and returns a `pin-invalid` advisory — treat that
  as a prompt to re-confirm and rewrite the pin.
