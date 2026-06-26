# Quartermaster contract

This document is the cross-cutting contract for the Quartermaster server and
its web UI. The instruction kits this project follows (`stack-fastapi-vuetify`,
`module-api-design`, `module-auth-oidc`, `module-auth-oidc-vue`,
`module-vue-vuetify`, `module-fastapi`) treat this file as the single anchor
for decisions that span the front and back ends. Read it before changing the
API surface, the authentication flow, the runtime configuration, or the shared
data types.

## Configuration

All server configuration is read from environment variables, namespaced with
the **`QM_` prefix** (per `module-fastapi`). The canonical loader is
`app.config.Settings` (pydantic-settings, `env_prefix="QM_"`). A handful of
values are read at import/bootstrap time outside `Settings`
(`QM_KITS_ROOT` for the `/dav` mount, `QM_WEBUI_DIST`, `QM_LOG_LEVEL`,
`QM_LOG_CONFIG`, `QM_DEV_AUTH_ENABLED`); these use the same prefix explicitly
so the namespace is consistent everywhere.

Browser/SPA build-time variables follow the Vite convention and are **not**
prefixed with `QM_` (`VITE_*`); they are baked into, or injected at runtime
into, the front-end bundle and never read by the server's `Settings`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `QM_KEYCLOAK_URL` | yes | Base URL of the Keycloak server (no trailing slash). |
| `QM_KEYCLOAK_REALM` | yes | Realm that issues tokens. |
| `QM_RESOURCE_BASE_URL` | yes | Public origin (scheme+host) as reached by the browser; drives OAuth metadata + SPA redirect URIs. |
| `QM_KEYCLOAK_AUDIENCE` | no | Expected `aud` claim; unset skips audience validation. |
| `QM_KITS_ROOT` | no* | Kit catalog directory. Required at runtime (the catalog is external); the Docker image defaults it to `/data/kits`. |
| `QM_CLIENT_REGISTRY_PATH` / `QM_APP_TOKENS_PATH` | no | JSON state files; persist on the data volume in production. |
| `QM_DAV_REQUIRE_TLS` | no | Refuse WebDAV Basic over plain HTTP (default true). |
| `QM_WEBUI_DIST` | no | Built SPA directory; unset → SPA not served. |
| `QM_OAUTH_SCOPES` | no | Scopes advertised in OAuth metadata. |
| `QM_COPILOT_AUTH_ENABLED` / `QM_COPILOT_AUTH_TIMEOUT_SECONDS` | no | Fixed-header auth for clients that cannot present a bearer token. |
| `QM_TLS_CA_BUNDLE` / `QM_TLS_INSECURE_SKIP_VERIFY` | no | TLS verification for outbound Keycloak calls. |
| `QM_GITHUB_OWNER` / `QM_GITHUB_REPO` / `QM_GITHUB_TOKEN` / `QM_GITHUB_DEFAULT_ASSIGNEE` | no | Enable GitHub issue materialization for gap requests. |
| `QM_DEV_AUTH_ENABLED` / `QM_DEV_SHARED_SECRET` | no | **Dev only** — local auth bypass. Never set in production. |
| `QM_LOG_LEVEL` / `QM_LOG_CONFIG` | no | Runtime-configurable logging. |

`server/.env.example` enumerates every variable with inline guidance.

## REST API (`/api`)

Design follows `module-api-design`.

- **Media type.** All `/api` requests must send `Accept:
  application/vnd.instructions+json; v=1` (strict negotiation — bare
  `application/json`/`*/*` → **406**). Every `/api` response carries the same
  vendor `Content-Type`. **API versioning is by media type (`v=`), never by
  URL path segment.** The `{version}` path segments under `/api/kits` are
  kit-catalog *major versions* (domain data), not API versions.
- **URLs are nouns**, alternating collection/resource nodes, no verbs, no file
  extensions.
- **Status codes.**
  - `POST` that creates a resource → **201 Created** with a `Location` header
    pointing at the new resource URL.
  - `PUT` is idempotent replacement → **200**; the resources here
    (`applicability`, sections) are addressed by a known key, so a created-vs-
    replaced distinction is not surfaced.
  - `DELETE` is idempotent → **204 No Content**, no body, and a no-op (still
    204) when the target is already absent.
- **PATCH strategy.** Not currently offered. If partial updates are added, use
  JSON Merge Patch (RFC 7386) with the vendor media type; record the decision
  here first.
- **Long-running jobs.** None today. If added, return `202 Accepted` with a
  `Location` pointing at a status resource under `/api`.
- **Client identification.** Non-browser clients must register their
  `User-Agent` (`POST /api/clients`, idempotent) before calling `/api`;
  unregistered non-browser UAs get **403** pointing at the registration route.
  This is an identification aid, not an auth gate.
- **Errors** are `{"detail": "..."}` with the mapped status (404/409/422/400).

## Authentication

Architecture follows `module-auth-oidc`; the Python resource server follows
`module-auth-oidc-python`; the SPA follows `module-auth-oidc-vue`.

- **Provider strategy: Option A — true OIDC via Keycloak.** There is no
  `/auth/exchange` endpoint and no provider-adapter layer; the only IdP is
  Keycloak, a standards-compliant OIDC provider.
- **Resource server.** `JWTAuthMiddleware` validates RS256/ES256 bearer JWTs
  against the realm JWKS (cached, auto-rotating). `iss` is always verified;
  `aud` is verified when `QM_KEYCLOAK_AUDIENCE` is set. Only `/api` and `/kits`
  require auth; the SPA shell, `/config.js`, health probes, and the well-known
  documents are public. Validation is enforced in middleware (not a per-route
  `Depends`) because the protected surface is the mounted FastMCP ASGI app, not
  individual route handlers.
- **Public client + PKCE.** The browser runs the authorization-code + PKCE
  (S256) flow; the public client uses `token_endpoint_auth_method=none` and
  never holds a client secret.
- **Token storage (SPA).** Tokens are held by `oidc-client-ts` in
  `sessionStorage` (cleared when the tab closes; not shared across tabs) — a
  deliberate trade-off favouring reduced persistence over cross-tab silent SSO.
  Silent renew is enabled; a re-auth loop breaker trips after repeated 401s to
  avoid redirect storms.
- **Dev bypass.** `module-dev-auth-bypass` — two independent gates
  (`QM_DEV_AUTH_ENABLED`, `QM_DEV_SHARED_SECRET`), both off by default, inert in
  production, and the `/auth/dev/*` router is a plain 404 unless explicitly
  enabled.
- **WebDAV (`/dav`).** HTTP Basic `username:app-token`; app tokens are
  server-issued opaque secrets stored hashed and bound to the minting OIDC
  subject. Basic over non-TLS is refused unless `QM_DAV_REQUIRE_TLS=false`.

## Shared data types

The SPA's business-object interfaces (`webui/src/types/`) are the agreed shape
of the API payloads. They are currently hand-maintained and kept in sync with
the FastAPI/Pydantic response models by review; the OpenAPI document
(`/openapi.json`, served behind auth) is the reference. If drift becomes a
problem, generate the TS types from the OpenAPI schema rather than editing them
by hand.

## Runtime config (SPA)

Per `module-runtime-config-spa`, the SPA is built once and configured at
runtime: the server renders `/config.js` (`window.__APP_CONFIG__`) from
`Settings`, with `VITE_*` build-time values as a dev fallback. Only public,
non-secret values are exposed (Keycloak authority, public client id, redirect
URIs, same-origin API base). Security toggles (e.g. the dev-auth flag) are
never placed in the runtime global.
