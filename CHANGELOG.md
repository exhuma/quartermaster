# Changelog

All notable changes to the Quartermaster server are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/), and the
project aims to follow semantic versioning.

## Unreleased

### Added

- Harness-enforced `resolve_kits` adoption. Agents reliably call `resolve_kits`
  at session start but drift off it during ongoing edits: the server's guidance
  is correct but, left to model discretion, decays over a long session. Two
  fixes ship together. (1) The MCP `instructions` string and the `resolve_kits`
  docstring now carry an explicit, checkable **re-run trigger list** — call it
  again on a change/plan request, when starting a new subsystem/aspect, on a
  direction shift, and after a context compaction before editing — and state
  plainly that this is a standing behavior that stays reliable only when the
  client harness enforces it. (2) A new **harness enforcement** section on the
  Integrate page ships copy-pasteable Claude Code hooks that reproduce the
  pattern: a `UserPromptSubmit` reminder (plain stdout injected as context), a
  non-blocking `PreToolUse` edit nudge that emits an `additionalContext`
  envelope and stays silent once `resolve_kits` has run this session, and a
  `PostToolUse` recorder that flips that switch — per-session state keyed on the
  hook's `session_id` under a gitignored XDG cache dir. The page also documents
  equivalents for other agents from current research: opencode, Cursor, Cline
  and Windsurf expose hooks (with examples and caveats — notably opencode has no
  prompt-submit hook and may not fire tool hooks for MCP calls), while Continue,
  Aider and Zed are rules-only and get a strongly-worded trigger list instead.
  The canonical scripts live once under `webui/src/docs/claude-code/`, are
  inlined into the UI verbatim via Vite `?raw`, are exercised by
  `server/tests/test_claude_code_hooks.py`, and are dogfooded by this repo's own
  `.claude/settings.json`.
- Long-lived tokens for MCP bearer auth: app tokens (the same credentials used
  as the WebDAV Basic password) are now accepted as
  `Authorization: Bearer <token>` on the MCP mount and the REST API. This gives
  clients that can't refresh OAuth — notably opencode, whose refresh handling
  is unreliable — a stable credential that never expires. Validation is a
  fallback in `JWTAuthMiddleware`: a bearer value that is not a JWT is checked
  against the app-token store (constant-time, same as the DAV/metrics path) and
  binds to the minting user's subject, so private-kit ownership and roles are
  unchanged. No new store, endpoint, TTL, or scope — the existing
  `/api/app-tokens` mechanism is reused as-is. The token mint/list/revoke card
  is now a shared web-UI component surfaced on both the **Mount** and
  **Integration** pages, and the Integration page documents the bearer-token
  setup (opencode static-header config).
- Authorization with two roles — `editor` (admin: edits the shared catalog and
  grants/revokes editor from others) and `consumer` (read-only, the default).
  An IdP subject (`sub`) → role mapping is persisted as TOML
  (`QM_ROLE_STORE_PATH`, default `server/var/roles.toml`); unknown users
  default to `consumer`. Bootstrap editors are seeded via `QM_INITIAL_EDITORS`
  (comma-separated or JSON array of `sub`s) and can never be locked out. New
  endpoints: `GET /api/me`, editor-only `GET/PUT/DELETE /api/roles`. Web UI
  gains a **Users** admin screen and hides edit controls for consumers. See
  `MIGRATING-AUTHORIZATION.md`.
- Private kits: any authenticated user (consumers included — ownership, not
  role, is the gate) can author standalone kits under `QM_PRIVATE_KITS_ROOT`
  (default `server/var/private-kits/`), visible **only to the owner** across
  `list_kits`/`select_kits`/`resolve_kits`/`get_kit` over the MCP and never to
  anyone else (non-owner reads return 404). Managed via `/api/private-kits` and
  a **Private** web-UI screen. The shared trait vocabulary and embedding cache
  stay public-only, so private kits never poison them.
- Caller identity is now carried into FastMCP tool calls (via a context
  variable bound by a plain-ASGI wrapper at the `/kits` mount), which is what
  makes owner-only private-kit visibility work over the MCP.
- Metrics dashboard time-series granularity toggle: a Hourly/Daily switch next
  to the window selector re-buckets the "Tokens sent to clients" and "Catalog
  growth" charts. The 24h window defaults to hourly (`1h`) buckets, the 7d/30d
  windows to daily (`1d`); the switch overrides the default for the current
  window. `GET /api/metrics/overview` gains a `granularity` (`1h`/`1d`) query
  parameter (echoed in `meta.granularity`, falls back to `1d`). Daily catalog
  snapshots are forward-filled across hourly buckets so both chart series stay
  on one aligned x-axis.
- Multi-root kit catalogs ("layers"): compose several catalogs as an ordered
  base → overlay stack via `QM_KIT_LAYERS_FILE` (a TOML layers file; relative
  paths resolve against the file's directory). Kit-level shadowing (the
  highest-priority layer owns a kit entirely), with base-layer sections marked
  `binding = true` surviving shadowing. Each layer is addressable at
  `/api/kits/layers/<name>/...` and `/dav/<name>/`, and can be marked
  `readonly = true` (writes → HTTP 403). A single `QM_KITS_ROOT` is fully
  backward compatible (treated as one `default` layer; `/dav/` and `/api/kits`
  URLs unchanged). See `MIGRATING-KIT-LAYERS.md`.
- Hardening HTTP middleware (module-http-middleware-hardening): a per-request
  correlation ID (`X-Correlation-ID`, honoured inbound, echoed back, shared by
  every log line via a contextvar), the three standard security headers, an
  `X-Quartermaster-Version` response header, and one structured access-log line
  per request.
- Opt-in rate limiting on the client-registration and app-token-minting
  endpoints (HTTP 429 with the full RFC 6585 header set).
- Dedicated `GET /livez`, `GET /readyz`, and `GET /healthz` probes
  (module-observability-healthz) with a compact, security-minimized payload and
  503-on-fail. The existing `GET /health` remains as a liveness alias.
- Web UI build-identity strip (`BuildMeta.vue`): a source-repository link
  (module-github-link) and a commit chip + identicon (module-release-metadata),
  fed by build-time `VITE_GITHUB_REPO_URL` / `VITE_APP_COMMIT` /
  `VITE_APP_BUILD_TIME` ARGs wired through the Dockerfile, compose, and CI. Each
  element is hidden when its variable is absent.

### Security

- Kit mutations now require the `editor` role. Every kit-writing REST route and
  every WebDAV write method (`PUT`/`DELETE`/`MKCOL`/`MOVE`/`COPY`/`PROPPATCH`/
  `LOCK`) is gated → **HTTP 403** for consumers (default-deny). This closes the
  path where any authenticated user, or any minted app token, could modify the
  shared catalog. **Breaking for existing deployments** — set
  `QM_INITIAL_EDITORS` to keep editing; see `MIGRATING-AUTHORIZATION.md`.
- Ownership and roles now key on the stable Keycloak `sub` (immutable) rather
  than `preferred_username`. App tokens minted before this release should be
  revoked and re-minted (they only grant WebDAV/metrics access).
- The bearer-token 401 response no longer echoes the raw PyJWT exception text
  to the client (it is logged instead) — module-auth-oidc-python.

### Changed

- REST API: `POST` endpoints that create a resource now return a `Location`
  header (kit/version creation, client registration, app-token minting).
- The web UI now ships both a light and a dark Vuetify theme.

### Changed (breaking)

- REST API: `DELETE /api/kits/{name}/versions/{version}` and
  `DELETE .../sections/{section_id}` now return **204 No Content** with no body
  (previously 200 with the updated list). Fetch the collection with `GET` if
  you need the post-delete state. Both remain idempotent.
- **All server environment variables are now prefixed with `QM_`** (e.g.
  `KEYCLOAK_URL` → `QM_KEYCLOAK_URL`, `KITS_ROOT` → `QM_KITS_ROOT`,
  `LOG_LEVEL` → `QM_LOG_LEVEL`). This namespaces Quartermaster's configuration
  and avoids collisions with unrelated environment variables. **Action
  required:** rename every variable in your `.env`, Docker `ENV`, and
  `docker-compose` environment to the `QM_`-prefixed form. The browser/SPA
  build variables (`VITE_*`) are unchanged. See `contract.md` for the full
  configuration contract.

## v0.1.0 — Initial public release

First public release of **Quartermaster**, a self-hosted MCP server that
serves versioned AI instruction kits to coding agents.

- FastAPI + FastMCP backend exposing the kit MCP tools (`list_kits`,
  `get_kit_outline`, `get_kit`, `list_kit_versions`, `compare_kit_versions`)
  and the V2 trait-based selector (`list_available_traits`, `select_kits`,
  `explain_kit_candidate`).
- Keycloak-gated auth (`JWTAuthMiddleware`) terminating inside the
  application, with RFC 9728 / RFC 8414 OAuth discovery for OAuth-aware
  clients, and an optional fixed-header mode.
- REST admin API (`/api`) for kit CRUD, client registration, integration
  discovery, and app-token management; embedded WebDAV authoring at `/dav`.
- Vue 3 + Vuetify single-page web UI for kit management and MCP integration
  setup.
- The kit catalog is decoupled from the server: supplied at runtime via
  `QM_KITS_ROOT` and never bundled into the image.
- Container image published to GitHub Container Registry.
