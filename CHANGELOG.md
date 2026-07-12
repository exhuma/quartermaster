# Changelog


## Release 2026.7.12 (2026-07-12)

A public pre-login landing page and a tactical navy/brass redesign 
make
the web UI legible before sign-in, and repositories can now pin 
the kit
version they expect via a repo-side `.quartermaster.toml`. A 
single
malformed kit no longer takes the whole catalog down — it is 
isolated,
flagged in the UI, and skipped by selection.



### Added
- ☆ **[MCP] Per-repo kit version pinning via a repo-side
  `.quartermaster.toml`** *@ 2026.7.12a1*

  A repository can pin the kit version it expects in a `.quartermaster.toml`. Then `resolve_kits`/`get_kit` honour that pin so a repo stays on a known kit revision.

- [UI] Broken kits surfaced in the kit list *@ 2026.7.12a3*

  The kit list flags a malformed kit with an alert row and its load error (and no detail link) so it can be found and fixed.

- [UI] Public pre-login landing page *@ 2026.7.12a1*

  A public landing page now greets visitors before sign-in, so the product is legible without authenticating first.


### Changed
- [UI] Tactical navy/brass redesign with light and dark theming *@
  2026.7.12a1*

  The web UI was restyled with a coherent navy/brass palette across both the light and dark Vuetify themes.


### Fixed
- ☆ **[MCP] A broken kit no longer takes down the whole catalog** *@
  2026.7.12a3*

  A kit whose instructions index is missing or malformed is now isolated and excluded from selection instead of aborting the entire catalog load, so `list_kits`/`resolve_kits` keep serving every healthy kit.

- [UI] Bare `/docs` reaches the documentation site *@ 2026.7.12a3*

  Visiting `/docs` now redirects to the rendered docs index instead of returning the app shell, and a "Docs" link was added to the top navigation.


## Release 2026.7.4 (2026-07-04)

### Added
- [MCP] MCP prompt templates bundled as package markdown *@
  2026.7.4a1*

  The canned MCP prompts are now maintained as bundled markdown templates rather than inline strings, so the prompt text delivered to clients is easier to review and extend.


## Release 2026.7.3 (2026-07-03)

### Added
- ☆ **[MCP] Harness-enforced `resolve_kits` re-run triggers** *@
  2026.7.3a3*

  The MCP `instructions` string and the `resolve_kits` docstring now carry an explicit re-run trigger list: call it again on a change/plan request, when starting a new subsystem, on a direction shift, and after a context compaction.

- ☆ **[MCP] App tokens accepted as `Authorization: Bearer` on the MCP
  mount** *@ 2026.7.3a2*

  Long-lived app tokens now work as bearer credentials on the MCP mount and REST API, giving clients that cannot refresh OAuth (notably opencode) a stable credential.

- [UI] Integrate page ships copy-pasteable agent enforcement hooks *@
  2026.7.3a3*

  The Integrate page gained a harness-enforcement section with ready-to-paste Claude Code hooks (and guidance for opencode, Cursor, Cline, Windsurf and rules-only agents) that keep `resolve_kits` firing throughout a session.


### Fixed
- [UI] Metrics time-series render on a real UTC time axis *@
  2026.7.3a2*

  The metrics dashboard now plots its series against an actual UTC time axis instead of evenly-spaced buckets.


## Release 2026.7.2 (2026-07-02)

### Added
- ☆ **[MCP] Guided auto-evolution: catalog-recall gap detection** *@
  2026.7.2a3*

  When trait inference finds nothing, `resolve_kits` now runs a fuzzy recall pass and reports a genuine catalog gap. New tools `check_existing_gap_issue` and `request_clarification_or_addition` let an agent surface the gap to maintainers.

- [MCP] Per-user memory tools `get_my_memory` / `reset_my_memory` *@
  2026.7.2a3*

  A bounded, per-caller familiarity profile derived from your own resolve history nudges kit ranking (never overriding a real trait match). It is viewable and resettable over the MCP.


### Changed
- [UI] Catalog-growth metrics chart gains a domain selector *@
  2026.7.2a1*

  The catalog-growth chart can now be filtered by domain.


## Release 2026.7.1 (2026-07-01)

Authorization (editor/consumer roles) and owner-only private kits land

together — the largest behavioural change since the initial release.



### Added
- ☆ **[MCP] Owner-only private kits over the MCP** *@ 2026.7.1a4*

  Any authenticated user can author private kits that are visible only to them across `list_kits`, `select_kits`, `resolve_kits` and `get_kit`. Non-owner reads return 404 and private kits never poison the shared trait vocabulary.

- [UI] Users admin screen and Private kits screen *@ 2026.7.1a4*

  The web UI gained a Users admin screen (role management) and a Private screen for authoring owner-only kits. Edit controls are hidden for consumers.

- [API] Editor/consumer roles with `GET /api/me` and `/api/roles` *@
  2026.7.1a4*

  Two roles are introduced — editor (manages the shared catalog and grants roles) and consumer (read-only default) — with new endpoints to read your role and manage the subject-to-role mapping.

- [UI] Metrics dashboard 1h/1d granularity toggle *@ 2026.7.1a3*

  An Hourly/Daily switch re-buckets the token and catalog-growth charts. `GET /api/metrics/overview` gained a `granularity` parameter.


### Changed
- [UI] Kit-layer chip and centred app-bar navigation *@ 2026.7.1a2*

  The active kit layer is shown as a chip and the top navigation was centred.


### Security
- [Security] Kit mutations now require the editor role (HTTP 403 for
  consumers) *@ 2026.7.1a4*

  Every kit-writing REST route and WebDAV write method is gated to editors (default-deny). Breaking for existing deployments: set QM_INITIAL_EDITORS to keep editing.


## Release 2026.6.30 (2026-06-30)

### Added
- [UI] Always-on local metrics dashboard (independent of
  OpenTelemetry) *@ 2026.6.30a2*

  A built-in metrics dashboard now works without any external OTEL collector.

- [MCP] Onboarding prompts *@ 2026.6.30a1*

  New canned MCP prompts guide first-time integration.


### Changed
- ☆ **[MCP] `resolve_kits` aligned with MCP prompts, sampling and
  elicitation** *@ 2026.6.30a1*

  Trait inference now prefers the connecting client's own LLM via MCP sampling (degrading to embeddings, then a lexical floor) and can elicit a clarification. A diagnostic mode reports which engine produced the result.


## Release 2026.6.26 (2026-06-26)

Broad hardening pass plus the introduction of the one-shot 
`resolve_kits`
discovery tool. Note the breaking `QM_` environment-
variable prefix and
the DELETE-returns-204 API change.



### Added
- ☆ **[MCP] `resolve_kits` one-shot discovery tool** *@ 2026.6.26a4*

  Free-text task in, ranked kits out with each kit's always_load sections already inlined. Server-side trait inference collapses the whole list/select/explain/outline/get discovery loop into a single call.

- [UI] Build-identity strip: source-repository link and commit chip *@
  2026.6.26a3*

  The web UI can show a link to the source repository plus a commit chip and identicon, each hidden when its build variable is absent.

- [Ops] Health probes `/livez`, `/readyz`, `/healthz` and hardening
  middleware *@ 2026.6.26a3*

  Dedicated liveness/readiness probes, a per-request correlation id, standard security headers, an X-Quartermaster-Version header, and opt-in rate limiting on registration/token endpoints.

- [UI] Dark Vuetify theme alongside the existing light theme *@
  2026.6.26a3*

  The web UI ships both a light and a dark theme.

- [MCP] Tool-call audit logging *@ 2026.6.26a1*

  Every MCP tool call is now audit-logged on the server.


### Changed
- [MCP] Discovery surfaces now lead with `resolve_kits` *@
  2026.6.26a4*

  The tool docstrings and server instructions steer clients to `resolve_kits` as the default discovery entry point.

- [Ops] All server environment variables are now prefixed with `QM_`
  *@ 2026.6.26a3*

  Configuration is namespaced (e.g. KEYCLOAK_URL becomes QM_KEYCLOAK_URL, KITS_ROOT becomes QM_KITS_ROOT). Breaking: rename every server variable to the QM_ form. VITE_* build variables are unchanged.

- [API] POST creates return a Location header, DELETE returns 204 No
  Content *@ 2026.6.26a3*

  Resource-creating POSTs now return a Location header. DELETE of a kit version or section returns 204 No Content with no body (breaking for clients that read the old 200 payload).


## Release 2026.6.25 (2026-06-25)

### Added
- [UI] opencode integration setup on the Integrate page *@
  2026.6.25a3*

  The Integrate page documents how to connect the opencode client.

- [Ops] Configurable TLS verification for Keycloak validation *@
  2026.6.25a2*

  TLS verification against the Keycloak realm can be configured for self-hosted / proxied setups.


## Release 0.1.0 (2026-06-25)

First public release of Quartermaster — a self-hosted MCP server that

serves versioned AI instruction kits to coding agents.



### Added
- [UI] Vue 3 + Vuetify web UI for kit management and MCP integration

  A single-page web UI for browsing/managing kits and setting up MCP integration.

- [MCP] V2 trait-based selector: list_available_traits, select_kits,
  explain_kit_candidate

  Kits are ranked against a project's traits (languages/frameworks/capabilities/contexts) with requires/excludes/priority.

- [MCP] Initial kit toolset: list_kits, get_kit_outline, get_kit,
  list_kit_versions, compare_kit_versions

  First public release of the kit MCP tools for loading versioned instruction kits on demand.


### Support
- [Ops] Keycloak-gated auth, REST admin API and embedded WebDAV
  authoring

  Auth terminates in the application (Keycloak JWTs), with a REST admin API and a WebDAV authoring endpoint. The kit catalog is supplied at runtime and never bundled.


