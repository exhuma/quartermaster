# Development

How to run the project locally: the FastAPI backend (MCP + REST API +
WebDAV), the Vue web UI, and the test suites.

## Prerequisites

- **Python** with [`uv`](https://docs.astral.sh/uv/) (backend).
- **Node 22+ and npm** (web UI).
- A **Keycloak realm** — for production-like auth. For day-to-day local
  work you can skip it entirely with the
  [dev auth bypass](#dev-auth-bypass-no-keycloak).
- Docker is only needed for the production-style container build (see the
  README's self-hosting section), not for day-to-day development.

## Repository layout

| Path | What it is |
|---|---|
| `server/` | FastAPI + FastMCP backend. Serves the MCP endpoint, the `/api` REST admin API, the `/dav` WebDAV authoring endpoint, and (in production) the built SPA. |
| `webui/` | The Vue 3 + Vuetify single-page app. |

The instruction-kit catalog — the **data** the server serves — lives in a
**separate repository** and is never bundled with this server. The catalog
is decoupled from the core: the server reads it from `KITS_ROOT`, which must
point at your kit-catalog checkout (dev) or the mounted volume (production).

## Backend (API + MCP)

```bash
cd server
uv sync                       # install deps (incl. dev group)
cp .env.example .env          # then edit — see required vars below
uv run uvicorn app.main:app --reload
```

The backend listens on <http://localhost:8000>.

**Required settings** (in `server/.env`, or as env vars): `KEYCLOAK_URL`,
`KEYCLOAK_REALM`, `RESOURCE_BASE_URL`, `KITS_ROOT`. For local use,
`RESOURCE_BASE_URL` can be `http://localhost:8000`, and `KITS_ROOT` must
point at a local checkout of your kit catalog. Without a `.env` you can pass
them inline:

```bash
KEYCLOAK_URL=https://auth.example.com \
KEYCLOAK_REALM=master \
RESOURCE_BASE_URL=http://localhost:8000 \
KITS_ROOT=/path/to/your/kit-catalog \
uv run uvicorn app.main:app --reload
```

Quick checks:

```bash
curl http://localhost:8000/health           # → {"status":"ok"}
curl -X POST http://localhost:8000/kits/mcp # → 401 (auth required)
```

Run the backend tests:

```bash
cd server
uv run pytest
```

> The real-catalog tests resolve the catalog from `KITS_ROOT` and skip when
> it is absent, so they pass even against an empty/decoupled checkout.

## Web UI (SPA)

There are two ways to run the UI. Use **A** for active UI work (hot
reload); use **B** to verify how the SPA behaves when served by the backend
in production.

### A. Vite dev server (recommended for UI work)

```bash
cd webui
npm install
cp .env.example .env   # set VITE_OIDC_AUTHORITY and VITE_OIDC_CLIENT_ID
npm run dev            # → http://localhost:5173
```

`VITE_OIDC_AUTHORITY` and `VITE_OIDC_CLIENT_ID` are **required** — the app
fails loudly at boot if they are missing. `VITE_OIDC_AUTHORITY` is
`{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}`.

Run the **backend too** (previous section): the Vite dev server proxies
`/api` and `/kits` to `http://localhost:8000`, so the browser sees one
origin and there are no CORS hurdles. In dev the runtime `config.js` is an
empty stub, so configuration comes from the `VITE_*` values.

Frontend checks:

```bash
npm run test        # vitest
npm run type-check  # vue-tsc (no emit)
npm run build       # type-check + production bundle into dist/
```

### B. Production-style (SPA served by FastAPI)

Build the SPA, then point the backend at the build. The server then serves
the UI, the API, the MCP endpoint, and a runtime-rendered `/config.js`
(from its own settings) all from <http://localhost:8000>:

```bash
cd webui && npm run build
cd ../server
WEBUI_DIST=../webui/dist \
KEYCLOAK_URL=https://auth.example.com \
KEYCLOAK_REALM=master \
RESOURCE_BASE_URL=http://localhost:8000 \
uv run uvicorn app.main:app --reload
```

## Dev auth bypass (no Keycloak)

The project enforces Keycloak auth everywhere — but for local development
you can bypass it instead of standing up an IdP. The bypass accepts
self-minted **HS256** dev tokens alongside real tokens and is **inert in
production**: it is off by default, gated independently on the backend and
frontend, and the frontend half is dead-code-eliminated from production
builds (verified by `npm run check:no-dev-auth`).

Enable it on **both** sides:

```bash
# server/.env — local only, never in production
DEV_AUTH_ENABLED=true
DEV_SHARED_SECRET=any-long-random-local-string
```

```bash
# webui/.env — local only
VITE_DEV_AUTH=true
```

Now `npm run dev` auto-logs-in by fetching a dev token from the server's
`/auth/dev/token` endpoint — no Keycloak, no `VITE_OIDC_*` needed. For
scripts/E2E, mint a token directly:

```bash
cd server
DEV_AUTH_ENABLED=true DEV_SHARED_SECRET=... uv run python -m app.dev_auth
```

How it stays safe in production: `DEV_SHARED_SECRET` unset ⇒ HS256 tokens
rejected; `DEV_AUTH_ENABLED` unset ⇒ `/auth/dev/*` is a 404; and the SPA's
`devAuth` gate folds to `false` at build time, so the dev-login code never
ships. Never set any of these in a deployed environment.

## Keycloak for the web UI

To develop against real OIDC (instead of the bypass above), the browser UI
uses authorization code + PKCE, so you need a realm with a **public**
client:

- **Client ID:** `quartermaster-webui` (override via `VITE_OIDC_CLIENT_ID`
  for the SPA and `WEBUI_KEYCLOAK_CLIENT_ID` for the backend's `/config.js`).
- **Client authentication:** OFF (public). PKCE method `S256`.
- **Standard flow:** ON.
- **Valid redirect URIs:** `http://localhost:5173/auth/callback` (Vite dev)
  and/or `http://localhost:8000/auth/callback` (production-style).
- **Web origins:** `http://localhost:5173` (and `http://localhost:8000`).

Without Keycloak you can still run the backend, the test suites, and the
production build — but the interactive browser UI needs a working OIDC
provider. To exercise the API directly without the UI, obtain a token via
the `client_credentials` flow (see the README's "Obtaining a token").

## WebDAV authoring endpoint (local)

`/dav` lets you mount the kit catalog as a drive and edit kits with a
coding agent; writes land on `KITS_ROOT` and are visible to the MCP
immediately. It uses HTTP Basic (`username` : `app-token`) and **requires
TLS by default**. For local non-TLS testing, disable that guard:

```bash
DAV_REQUIRE_TLS=false   # in server/.env — local testing only
```

Mint an app token from the UI's **Mount** page (you must be signed in),
then mount with any username and the token as the password — for example:

```bash
rclone config           # WebDAV remote, vendor=other, url=http://localhost:8000/dav
rclone mount kits: /mnt/kits --vfs-cache-mode writes
```
