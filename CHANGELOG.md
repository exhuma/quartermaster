# Changelog

All notable changes to the Quartermaster server are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/), and the
project aims to follow semantic versioning.

## Unreleased

### Added

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
