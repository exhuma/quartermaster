# Development

How to run the project locally: the FastAPI backend (MCP + REST API +
WebDAV), the Vue web UI, and the test suites.

## Fast start (no Keycloak)

If you have [`task`](https://taskfile.dev) installed, `task setup && task run`
boots the backend and web UI together with the [dev-auth
bypass](#dev-auth-bypass-no-keycloak) already enabled — no manual env editing
and no Keycloak. The rest of this document is the fuller reference behind that
shortcut.

The server serves kits from a directory (`QM_KITS_ROOT`) and is not bundled
with one, so create a throwaway catalog with a single example kit first. Drop
it into `server/var/kits/` (the path `task run` uses):

```bash
KIT=server/var/kits/hello-kit
mkdir -p "$KIT/v1/instructions"

cat > "$KIT/applicability.json" <<'JSON'
{
  "kit_type": "module",
  "summary": "A minimal example kit for trying out Quartermaster.",
  "domains": ["example"], "languages": [], "frameworks": [], "contexts": [],
  "requires": { "languages": [], "frameworks": [], "capabilities": [], "contexts": [] },
  "excludes": { "languages": [], "frameworks": [], "capabilities": [], "contexts": [] },
  "optional_signals": ["demo"], "related_kits": [], "priority": 10
}
JSON

cat > "$KIT/CHANGELOG.md" <<'MD'
# Changelog
## v1.0.0
- Initial example kit.
MD

cat > "$KIT/v1/instructions/index.toml" <<'TOML'
summary = "A minimal example kit demonstrating the section format."

[[sections]]
file = "invariant.md"
title = "Invariants"
gloss = "The one rule this example kit teaches."
always_load = true
TOML

cat > "$KIT/v1/instructions/invariant.md" <<'MD'
# Invariants
- This is a demo kit. Replace it with your own — see the kit-authoring guide.
MD
```

Then `task setup && task run` and open <http://localhost:5173>: you are
auto-logged-in (no Keycloak) and the kit list shows **hello-kit**. Authoring
real kits is covered in [Authoring kits](../user/authoring-kits.md). The
manual, Task-free equivalents are the sections below.

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
is decoupled from the core: the server reads it from `QM_KITS_ROOT`, which must
point at your kit-catalog checkout (dev) or the mounted volume (production).

## Backend (API + MCP)

```bash
cd server
uv sync                       # install deps (incl. dev group)
cp .env.example .env          # then edit — see required vars below
uv run uvicorn app.main:app --reload
```

The backend listens on <http://localhost:8000>.

**Required settings** (in `server/.env`, or as env vars): `QM_KEYCLOAK_URL`,
`QM_KEYCLOAK_REALM`, `QM_RESOURCE_BASE_URL`, `QM_KITS_ROOT`. For local use,
`QM_RESOURCE_BASE_URL` can be `http://localhost:8000`, and `QM_KITS_ROOT` must
point at a local checkout of your kit catalog. Without a `.env` you can pass
them inline:

```bash
QM_KEYCLOAK_URL=https://auth.example.com \
QM_KEYCLOAK_REALM=master \
QM_RESOURCE_BASE_URL=http://localhost:8000 \
QM_KITS_ROOT=/path/to/your/kit-catalog \
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

> The real-catalog tests resolve the catalog from `QM_KITS_ROOT` and skip when
> it is absent, so they pass even against an empty/decoupled checkout.

## Optional GitHub integration

The only part of the server that makes outbound calls to GitHub is the pair of
gap-request MCP tools (`check_existing_gap_issue` and
`request_clarification_or_addition`), which materialize kit-extension requests
as GitHub issues. They are registered — and therefore visible to coding
agents — **only when `QM_GITHUB_OWNER`, `QM_GITHUB_REPO`, and `QM_GITHUB_TOKEN` are all
set**. Leave them unset for a fully self-hosted / air-gapped install: the tools
are not exposed at all, the server never reaches out to GitHub, and the MCP
instructions automatically omit the gap-filing step. Everything else (kit
discovery, selection, and loading) works unchanged.

## Logging

Logging is configured at startup from the environment, so logs can be
redirected to disk, logstash, syslog, or a custom HTTP endpoint **without
rebuilding the image** — mount a config file and set an env var.

- `QM_LOG_LEVEL` — level for the default colored console output (used only when
  `QM_LOG_CONFIG` is unset). Defaults to `INFO`.
- `QM_LOG_CONFIG` — path to a **TOML** file holding a standard
  [`logging.config.dictConfig`](https://docs.python.org/3/library/logging.config.html#logging-config-dictschema)
  schema. When set, it takes full control of logging.

Set `disable_existing_loggers = false` so the uvicorn/app loggers survive. The
stdlib ships no JSON formatter, so a JSON-lines formatter is bundled at
`app.logging_config.JsonLinesFormatter` — reference it via dictConfig's `()`
factory key. Example writing one JSON object per line to a rotating file:

```toml
# logging.toml — mount it and set QM_LOG_CONFIG=/data/logging.toml
version = 1
disable_existing_loggers = false

[formatters.jsonlines]
"()" = "app.logging_config.JsonLinesFormatter"

[handlers.file]
class = "logging.handlers.RotatingFileHandler"
formatter = "jsonlines"
filename = "/var/log/quartermaster/app.log"
maxBytes = 10485760      # 10 MiB per file
backupCount = 5

[root]
level = "INFO"
handlers = ["file"]
```

Each line in `app.log` is then a single JSON object, e.g.:

```json
{"ts": "2026-06-26T10:15:00+0000", "level": "INFO", "logger": "app.mcp_audit", "message": "mcp_audit event=initialize session=… client=…"}
```

The log directory must exist and be writable (mount it into the container).
Other stdlib handlers work the same way — `SocketHandler` for logstash,
`SysLogHandler` for syslog, `HTTPHandler` for a custom endpoint. (An
OpenTelemetry handler needs its package baked into a derived image and is out
of scope for the stock image.)

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
`{QM_KEYCLOAK_URL}/realms/{QM_KEYCLOAK_REALM}`.

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
QM_WEBUI_DIST=../webui/dist \
QM_KEYCLOAK_URL=https://auth.example.com \
QM_KEYCLOAK_REALM=master \
QM_RESOURCE_BASE_URL=http://localhost:8000 \
uv run uvicorn app.main:app --reload
```

## Dev auth bypass (no Keycloak)

The project enforces Keycloak auth everywhere — but for local development
you can bypass it instead of standing up an IdP. The bypass accepts
self-minted **HS256** dev tokens alongside real tokens and is **inert in
production**: it is off by default, gated independently on the backend and
frontend, and the frontend half is dead-code-eliminated from production
builds (verified by `npm run check:no-dev-auth`).

`task run` enables this bypass automatically — it injects
`QM_DEV_AUTH_ENABLED` + `QM_DEV_SHARED_SECRET` (backend) and `VITE_DEV_AUTH`
(frontend) for the dev servers, so a fresh clone auto-logs-in with no manual
setup. Disable it per-run with `QM_DEV_AUTH_ENABLED=false task run`. The manual
recipe below is for running the servers without Task.

Enable it on **both** sides:

```bash
# server/.env — local only, never in production
QM_DEV_AUTH_ENABLED=true
QM_DEV_SHARED_SECRET=any-long-random-local-string
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
QM_DEV_AUTH_ENABLED=true QM_DEV_SHARED_SECRET=... uv run python -m app.dev_auth
```

How it stays safe in production: `QM_DEV_SHARED_SECRET` unset ⇒ HS256 tokens
rejected; `QM_DEV_AUTH_ENABLED` unset ⇒ `/auth/dev/*` is a 404; and the SPA's
`devAuth` gate folds to `false` at build time, so the dev-login code never
ships. Never set any of these in a deployed environment.

## Keycloak for the web UI

To develop against real OIDC (instead of the bypass above), the browser UI
uses authorization code + PKCE, so you need a realm with a **public**
client:

- **Client ID:** `quartermaster-webui` (override via `VITE_OIDC_CLIENT_ID`
  for the SPA and `QM_WEBUI_KEYCLOAK_CLIENT_ID` for the backend's `/config.js`).
- **Client authentication:** OFF (public). PKCE method `S256`.
- **Standard flow:** ON.
- **Valid redirect URIs:** `http://localhost:5173/auth/callback` (Vite dev)
  and/or `http://localhost:8000/auth/callback` (production-style).
- **Web origins:** `http://localhost:5173` (and `http://localhost:8000`).

Without Keycloak you can still run the backend, the test suites, and the
production build — but the interactive browser UI needs a working OIDC
provider. To exercise the API directly without the UI, obtain a token via
the `client_credentials` flow (see the README's "Obtaining a token").

### Behind a port-forward or reverse proxy

When the SPA is served by the backend (production-style), the server renders
the OIDC **redirect URI** into `/config.js` from `QM_RESOURCE_BASE_URL`
(`<QM_RESOURCE_BASE_URL>/auth/callback`), and that value overrides the browser's
own origin. So if you reach the server at a different address than it listens
on — e.g. a port-forward `50007:8000` or a reverse proxy — set
`QM_RESOURCE_BASE_URL` to the **externally-reachable** origin you open in the
browser, not the in-container one:

```bash
# accessed via a 50007:8000 port-forward:
QM_RESOURCE_BASE_URL=http://localhost:50007
```

Then register `<QM_RESOURCE_BASE_URL>/auth/callback` (and that origin under
**Web origins**) in the Keycloak client. The same value also drives the OAuth
metadata URLs, so it stays consistent for MCP clients. (This only affects the
production-style/served-SPA mode; the Vite dev server uses its own origin.)

## WebDAV authoring endpoint (local)

`/dav` lets you mount the kit catalog as a drive and edit kits with a
coding agent; writes land on `QM_KITS_ROOT` and are visible to the MCP
immediately. It uses HTTP Basic (`username` : `app-token`) and **requires
TLS by default**. For local non-TLS testing, disable that guard:

```bash
QM_DAV_REQUIRE_TLS=false   # in server/.env — local testing only
```

Mint an app token from the UI's **Mount** page (you must be signed in),
then mount with any username and the token as the password — for example:

```bash
rclone config           # WebDAV remote, vendor=other, url=http://localhost:8000/dav
rclone mount kits: /mnt/kits --vfs-cache-mode writes
```
