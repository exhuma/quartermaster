# Quartermaster

**Quartermaster** is a self-hosted **MCP server** that serves versioned
**AI instruction kits** to coding agents over an authenticated HTTP
endpoint — so agents load architecture preferences, tooling choices, and
hard-won experience *on demand*, per task, without the kit files ever
residing in the target project repository.

> **What is MCP?** The [Model Context Protocol][mcp] is an open standard
> that lets AI assistants discover and call tools exposed by a server.
> Quartermaster exposes its kit catalog as MCP tools, so any MCP-aware
> coding tool (Claude Code, VS Code/Copilot, Cursor, …) can query it.

Quartermaster ships as two parts:

- **`server/`** — a FastAPI + FastMCP backend exposing the MCP endpoint,
  a `/api` REST admin API, and a `/dav` WebDAV authoring endpoint.
- **`webui/`** — a Vue 3 + Vuetify single-page app for kit CRUD, MCP
  integration instructions, and local WebDAV authoring.

**The kit catalog is *not* part of this repository.** Kits are *data*,
supplied at runtime from a separate kit-catalog checkout (dev) or a
mounted volume (production) via the `QM_KITS_ROOT` setting. This keeps the
releasable server image independent of any (possibly private) kit content.

Running it locally? See [`DEVELOPMENT.md`](DEVELOPMENT.md).

---

## Quick start

**Just want to try it locally, without Keycloak?** Follow
**[QUICKSTART.md](QUICKSTART.md)** — server + web UI running in a few minutes
using the built-in dev-auth bypass.

### Run with Docker (production-style)

This path uses real authentication, so it needs a Keycloak realm and a kit
catalog to mount:

```bash
# 1. Build the image (build context is the repository ROOT).
docker build -f server/Dockerfile . -t quartermaster

# 2. Run it, pointing QM_KITS_ROOT at your own kit-catalog checkout.
docker run --rm -p 8000:8000 \
  -e QM_KEYCLOAK_URL=https://your-keycloak.example.com \
  -e QM_KEYCLOAK_REALM=your-realm \
  -e QM_RESOURCE_BASE_URL=http://localhost:8000 \
  -e QM_KITS_ROOT=/data/kits \
  -v /path/to/your/kit-catalog:/data/kits \
  quartermaster

# 3. Check it is up.
curl -s http://localhost:8000/livez
```

Quartermaster exposes several health probes:

- `GET /livez` — liveness (the process is up). `GET /health` is a
  backward-compatible alias.
- `GET /readyz` — readiness (the kit catalog is present and loadable).
- `GET /healthz` — full health, including Keycloak reachability.

The MCP endpoint is then served (authenticated) at
`http://localhost:8000/kits/mcp`. Prefer the prebuilt image? Pull a
**channel** (`:stable`, `:beta`, `:alpha`) or a pinned version from
`ghcr.io/exhuma/quartermaster` instead of building — see
[RELEASING.md](RELEASING.md) for the versioning and channel scheme. For a
production deployment behind Traefik, see
[Self-hosting with Docker + Traefik](#self-hosting-with-docker--traefik).

---

## MCP server

### What it does

The server speaks the [Model Context Protocol][mcp] (Streamable HTTP
transport) and exposes these kit tools (plus the trait-selection tools
`list_available_traits`, `select_kits`, and `explain_kit_candidate`):

| Tool | Description |
|---|---|
| `list_kits()` | Returns names, one-line descriptions, available versions, and the latest version of all kits. |
| `get_kit_outline(name, version?)` | Returns a cheap section map (titles, glosses, `always_load` flags, byte sizes) so an agent can pick which sections to load. |
| `get_kit(name, version?, sections?)` | Returns Markdown for the named kit. Pass `sections` to load only specific sections; omit it for the full guide. Defaults to the latest major version. |
| `list_kit_versions(name)` | Returns the sorted list of available major versions for a single kit. |
| `compare_kit_versions(name, from_version, to_version)` | Summarises changelog entries between two versions and warns when any change would affect end-users. |

Every request to the MCP endpoint must be authenticated.  By default this
means `Authorization: Bearer <token>` with a valid Keycloak-issued JWT.
Optionally, fixed headers (`X-Client-Id` + `X-Client-Secret`) can be
enabled for clients that cannot complete OAuth/JWT flows.

[mcp]: https://modelcontextprotocol.io

### How agents should use it

Kits are meant to be selected **per task**, not pinned once per project. Do
*not* hard-code a fixed kit list in `CLAUDE.md` / `AGENTS.md`: a static list
loads too much or too little, and the traits a task touches often only emerge
during the conversation. For example, an app with no authentication plus a
request to "add auth" may resolve to OIDC only after some discussion — bringing
OIDC kits into scope that were irrelevant when the task began.

So for each new task an agent should:

1. **Discover coverage** — `list_available_traits` (the trait vocabulary) and
   `list_kits` (the available kits).
2. **Map the task to traits** — infer which traits the task touches from the
   repository and the developer's intent, revisiting as the direction firms up.
3. **Load matching guidance** — `select_kits` → `explain_kit_candidate` →
   `get_kit_outline` → `get_kit` (pulling only the sections the step
   needs), re-running when new traits come into scope mid-task.

The server ships this workflow as MCP-level `instructions`, so compliant
clients surface it automatically on connect. Hard-coding kits is acceptable
only when a project's relevant kits are genuinely stable.

A recurring failure mode is querying with generic or invented traits (`auth`,
`internal-service`, or `kubernetes` as a *context*) that miss the published
vocabulary, so a relevant kit scores poorly and the agent wrongly concludes
nothing applies. Two server-side surfaces steer agents past this at minimal
token cost: a one-line normalization invariant baked into the MCP
`instructions`, and an evolvable **`trait_selection_bootstrap`** prompt (fetch
via `list_prompts` → `get_prompt`) holding the compact operational routine.

To nudge agents toward this in **your own** repositories, add one short,
light-touch line to that repo's `AGENTS.md` (or `CLAUDE.md`):

```md
When quartermaster is available, treat its published trait vocabulary and
bootstrap guidance as the source of truth for kit discovery; normalize user
intent to supported traits before selection and retry when coverage is low.
```

That sentence names concepts, not tool or endpoint names, so it survives
Quartermaster's evolution. For the rationale behind each phrase — plus a more
explicit step-by-step block and a normalization table — see
[AGENTS_GUIDANCE.md](AGENTS_GUIDANCE.md).

### Architecture

```
Coding tool (VS Code / Cursor / Claude)
      │  HTTPS POST /kits/mcp
      │  Authorization: Bearer <token>
      ▼
Traefik (TLS termination only — no auth middleware)
      │  HTTP :8000
      ▼
quartermaster (FastAPI + FastMCP)
   ├─ JWTAuthMiddleware  ← validates RS256/ES256 JWT
   └─ POST /kits/mcp      ← MCP streamable-HTTP endpoint
         │
         └─ reads kit instructions/ section files from QM_KITS_ROOT
            (an external catalog mounted at /data/kits)
```

Authentication terminates **inside the application**.  Traefik handles
TLS only and carries no auth middleware for this service.

### Keycloak setup (per collaborator)

Each collaborator or unattended use-case gets its own dedicated
Keycloak service-account client.  This allows per-client revocation
without affecting other users.

1. Open your Keycloak Admin Console → **Clients** → **Create client**.
2. Set **Client ID** to something descriptive, e.g.
   `quartermaster-alice` or `quartermaster-ci`.
3. **Client authentication**: ON.
4. **Authentication flow**: enable **Service accounts roles** only
   (disable Standard Flow and Direct Access Grants unless you need
   interactive login for that collaborator).
5. Click **Save**.
6. On the **Credentials** tab, note the **Client secret**.
7. Repeat for each collaborator.

No special roles or groups are required.  Any valid token from the
configured realm is accepted.  To revoke access, disable or delete the
client.

#### Optional: audience claim

If you want to scope tokens so they are only valid for this server,
add an **Audience** mapper to the client:

- **Mapper type**: Audience
- **Included client audience**: `quartermaster`
- **Add to access token**: ON

Then set `QM_KEYCLOAK_AUDIENCE=quartermaster` in `server/.env`.

### Obtaining a token

Collaborators run this command to fetch a short-lived access token and
store it in their shell environment.  Keycloak service-account tokens
expire after the realm's configured token lifespan (default 5 minutes;
consider extending to 24 hours for service accounts via
**Realm settings → Tokens → Access Token Lifespan**).

```bash
export QUARTERMASTER_TOKEN=$(
  curl -s -X POST \
    "${QM_KEYCLOAK_URL}/realms/${QM_KEYCLOAK_REALM}/protocol/openid-connect/token" \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "grant_type=client_credentials" \
    -d "client_id=${KC_CLIENT_ID}" \
    -d "client_secret=${KC_CLIENT_SECRET}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
)
```

Save `KC_CLIENT_ID`, `KC_CLIENT_SECRET`, and `QM_KEYCLOAK_URL`/
`QM_KEYCLOAK_REALM` in your shell profile or a secrets manager; never in
the project repository.

### Optional: fixed-header auth for Copilot coding agent

If your Copilot coding-agent integration sends fixed headers instead of
bearer tokens, enable this mode in `server/.env`:

```bash
QM_COPILOT_AUTH_ENABLED=true
QM_COPILOT_AUTH_TIMEOUT_SECONDS=3.0
```

The server validates `X-Client-Id` and `X-Client-Secret` against
Keycloak by calling the token endpoint with
`grant_type=client_credentials`. Revocation and secret rotation are
therefore controlled in the IDP.

Then configure repository MCP settings in GitHub with matching headers:

```json
{
  "mcpServers": {
    "quartermaster": {
      "type": "http",
      "url": "https://quartermaster.example.com/kits/mcp",
      "tools": [
        "list_kits",
        "get_kit_outline",
        "get_kit",
        "list_kit_versions",
        "compare_kit_versions"
      ],
      "headers": {
        "X-Client-Id": "$COPILOT_MCP_CLIENT_ID",
        "X-Client-Secret": "$COPILOT_MCP_CLIENT_SECRET"
      }
    }
  }
}
```

Set `COPILOT_MCP_CLIENT_ID` and `COPILOT_MCP_CLIENT_SECRET` as secrets
in the repository's `copilot` environment.

### Integrating with coding tools

#### Claude Code (interactive OAuth — no Dynamic Client Registration)

Claude Code authenticates to remote MCP servers over OAuth. It normally
relies on RFC 7591 **Dynamic Client Registration** (DCR), but it does
**not** require it: Claude Code also accepts a **pre-configured public
client** and performs an Authorization Code + **PKCE** flow against
Keycloak. This keeps DCR disabled on Keycloak (recommended) while giving
collaborators browser-based SSO with automatic token refresh — no
long-lived secret to copy around.

**One-time Keycloak setup** — create a single *public* client in the realm:

- **Clients → Create client** → Client ID e.g. `quartermaster-cli`.
- **Client authentication: OFF** (public client).
- **Authentication flow:** Standard flow ON; Direct access grants OFF.
- **Advanced → Proof Key for Code Exchange Code Challenge Method = `S256`**
  (forces PKCE).
- **Valid redirect URIs:** exactly `http://localhost:8080/callback`.
  Keycloak does not support wildcard ports for loopback redirects, so the
  port is pinned (see `--callback-port` below). `http` on `localhost` is
  permitted by Keycloak.
- Leave **Lightweight access token** OFF so the server can validate the
  RS256 JWT locally against the realm JWKS.

This client is shared by all collaborators; it mints no secret and can
only complete a browser PKCE login with the registered loopback redirect.

**Connect Claude Code:**

```bash
claude mcp add --transport http quartermaster \
  https://quartermaster.example.com/kits/mcp \
  --client-id quartermaster-cli --callback-port 8080
```

A browser window opens for the Keycloak login; Claude Code stores and
refreshes the token automatically. Verify with `/mcp` inside Claude Code,
then call `list_kits` / `get_kit`.

For **headless/CI** use where no browser is available, use the
service-account `client_credentials` flow instead and pass the token as a
header (mutually exclusive with OAuth — when an `Authorization` header is
set, Claude Code does not fall back to the OAuth flow):

```bash
claude mcp add --transport http quartermaster \
  https://quartermaster.example.com/kits/mcp \
  --header "Authorization: Bearer $QUARTERMASTER_TOKEN"
```

#### VS Code (GitHub Copilot)

Add to the **project** `.vscode/mcp.json` (safe to commit — contains
no secrets):

```json
{
  "servers": {
    "quartermaster": {
      "type": "http",
      "url": "https://quartermaster.example.com/kits/mcp",
      "headers": {
        "Authorization": "Bearer ${env:QUARTERMASTER_TOKEN}"
      }
    }
  }
}
```

`${env:QUARTERMASTER_TOKEN}` is resolved from the shell
environment at connection time.

#### Cursor

Add to `~/.cursor/mcp.json` (user-global, not per-project):

```json
{
  "mcpServers": {
    "quartermaster": {
      "url": "https://quartermaster.example.com/kits/mcp",
      "headers": {
        "Authorization": "Bearer ${env:QUARTERMASTER_TOKEN}"
      }
    }
  }
}
```

#### Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json` (Linux) or
`~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS):

```json
{
  "mcpServers": {
    "quartermaster": {
      "type": "streamable-http",
      "url": "https://quartermaster.example.com/kits/mcp",
      "headers": {
        "Authorization": "Bearer ${env:QUARTERMASTER_TOKEN}"
      }
    }
  }
}
```

> **Note** — HTTP MCP support in Claude Desktop is subject to the
> version you are running.  Check the Claude Desktop release notes if
> the server does not appear.

#### opencode

opencode can connect either via interactive **OAuth** (browser SSO with token
refresh) or a **static bearer token** header. OAuth is nicer day-to-day; the
header is simplest for headless/CI.

##### Option A — OAuth (browser login)

Quartermaster advertises a **public** OAuth client: `authorization_code` +
PKCE (`S256`), no client secret, no Dynamic Client Registration. The Keycloak
client **must be public** — a confidential client (one with a secret) passes
the browser step but fails the token exchange with `invalid_client`.

1. In Keycloak, configure the client as **public**: Client authentication
   **OFF**, Standard flow **ON**, PKCE method **`S256`**.
2. Register opencode's OAuth callback in that client's **Valid redirect URIs**.
   opencode's default callback is `http://127.0.0.1:19876/mcp/oauth/callback`.
3. Add the server, answering **No** to "Do you have a client secret?", then
   authenticate:

   ```bash
   opencode mcp add      # type: remote
                         # url:  https://quartermaster.example.com/kits/mcp
                         # OAuth: yes; client id: <public-client-id>; secret: no
   opencode mcp auth quartermaster
   ```

   Open the printed URL (or let it launch a browser), approve, and opencode
   stores + refreshes the token. Verify with `opencode mcp debug quartermaster`.

**Customizing the redirect URI/port.** If `19876` is taken, or you tunnel a
specific port and want to pre-register it, set `redirectUri` under the
server's `oauth` config (recent opencode builds support this), then register
**that exact URI** in Keycloak:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "quartermaster": {
      "type": "remote",
      "url": "https://quartermaster.example.com/kits/mcp",
      "oauth": {
        "clientId": "<public-client-id>",
        "redirectUri": "http://127.0.0.1:3118/mcp/oauth/callback"
      }
    }
  }
}
```

opencode binds its callback listener to the host/port/path of `redirectUri`
and sends the same value as `redirect_uri`. If your opencode build predates
this option, register (or tunnel) the default `…:19876/…` URI instead.

##### Option B — static bearer token (no browser)

Disable OAuth and supply a Keycloak service-account token via a header
(opencode interpolates `{env:VAR}` at startup):

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "quartermaster": {
      "type": "remote",
      "url": "https://quartermaster.example.com/kits/mcp",
      "enabled": true,
      "oauth": false,
      "headers": {
        "Authorization": "Bearer {env:QUARTERMASTER_TOKEN}"
      }
    }
  }
}
```

Mint the token with the `client_credentials` flow (see
[Obtaining a token](#obtaining-a-token)) and export it before launching
opencode:

```bash
export QUARTERMASTER_TOKEN=$(
  curl -s -X POST \
    "${QM_KEYCLOAK_URL}/realms/${QM_KEYCLOAK_REALM}/protocol/openid-connect/token" \
    -d grant_type=client_credentials \
    -d client_id="${KC_CLIENT_ID}" \
    -d client_secret="${KC_CLIENT_SECRET}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])"
)
```

The header is read at startup, so the token must outlast your session —
extend the service-account **Access Token Lifespan** in Keycloak (e.g. to
24h), and re-export + restart opencode when it expires.

> **Troubleshooting.** If the browser shows "Authentication Successful" but
> opencode reports "OAuth completion failed", the token exchange failed —
> almost always because the Keycloak client is **confidential**; switch it to
> public (above). If Keycloak shows the token *was* issued and opencode still
> fails, you may have hit a known opencode bug ([#17822][oc-issue]); update
> opencode or use Option B.

[oc-issue]: https://github.com/anomalyco/opencode/issues/17822

### Self-hosting with Docker + Traefik

#### Build

Build context must be the **repository root**:

```bash
docker build -f server/Dockerfile . -t quartermaster
```

#### Configure

```bash
cd server
cp .env.example .env
# Edit .env — fill in QM_KEYCLOAK_URL, QM_KEYCLOAK_REALM, QM_RESOURCE_BASE_URL.
# QM_KITS_ROOT is set to /data/kits by docker-compose (the mounted catalog).
```

> **Set `QM_RESOURCE_BASE_URL` to the origin the browser/client actually
> reaches** (your public domain, or a `host:port` if you front the server
> with a port-forward or reverse proxy) — not the in-container port. The
> server derives the web UI's OIDC redirect URI from it
> (`<QM_RESOURCE_BASE_URL>/auth/callback`) and renders it into `/config.js` at
> runtime, so a mismatch breaks the browser login. Register that exact
> redirect URI in your Keycloak client.

#### Deploy

```bash
cd server
docker compose up -d
```

The `docker-compose.yml` expects:
- An external Docker network named `traefik-proxy`.
- A running Traefik v3 instance on that network with an entrypoint
  named `websecure` and a cert resolver named `letsencrypt`.
- The hostname label inside `docker-compose.yml` adapted to your
  domain (`ADAPT` comment marks the line).
- A bind-mount of your kit catalog at `/data/kits` (`ADAPT` comment
  marks the line).

For running the server **and the web UI** locally, see
[`DEVELOPMENT.md`](DEVELOPMENT.md). For running the container in production —
mounts, volumes, and a staged rollout of the `resolve_kits` inference (local
embeddings first, then an external LLM) — see [`OPERATIONS.md`](OPERATIONS.md).

### Configuration reference

Every operator-settable input is an environment variable prefixed `QM_`.
`server/.env.example` is a convenient annotated starting point you can copy
to `.env`, but the table below is the authoritative reference.

| Name | Required | Purpose | Default |
|---|---|---|---|
| `QM_KEYCLOAK_URL` | Yes | Base URL of Keycloak (no trailing slash). | — |
| `QM_KEYCLOAK_REALM` | Yes | Realm that issues tokens. | — |
| `QM_RESOURCE_BASE_URL` | Yes | Public origin (scheme + host) as reached by the browser; drives OAuth metadata and the SPA redirect URIs. | — |
| `QM_KEYCLOAK_AUDIENCE` | No | Expected `aud` claim; unset skips audience validation. | unset (no audience check) |
| `QM_KITS_ROOT` | No* | Kit catalog directory. Required at runtime (the catalog is external). | `/data/kits` (Docker image) |
| `QM_CLIENT_REGISTRY_PATH` | No | Registered-client state file. | `/data/client_registry.json` (Docker image) |
| `QM_APP_TOKENS_PATH` | No | Hashed WebDAV app-token store. | `/data/app_tokens.json` (Docker image) |
| `QM_DAV_REQUIRE_TLS` | No | Refuse WebDAV Basic credentials over plain HTTP. | `true` |
| `QM_WEBUI_DIST` | No | Built SPA directory; unset means the SPA is not served. | unset |
| `QM_OAUTH_SCOPES` | No | Space-separated scopes advertised in OAuth metadata. | `openid profile email` |
| `QM_TLS_CA_BUNDLE` | No | PEM CA bundle for outbound Keycloak TLS. | system trust store |
| `QM_TLS_INSECURE_SKIP_VERIFY` | No | Disable Keycloak TLS verification (POC only — never in production). | `false` |
| `QM_COPILOT_AUTH_ENABLED` | No | Accept fixed-header (`X-Client-Id`/`X-Client-Secret`) auth for clients that cannot present a bearer token. | `false` |
| `QM_COPILOT_AUTH_TIMEOUT_SECONDS` | No | Token-endpoint timeout for fixed-header auth. | `3.0` |
| `QM_GITHUB_OWNER` | No | GitHub owner for kit-gap issue materialization (all of owner/repo/token required to activate). | unset (feature off) |
| `QM_GITHUB_REPO` | No | GitHub repository for kit-gap issue materialization. | unset (feature off) |
| `QM_GITHUB_TOKEN` | No | GitHub token permitted to create issues in the configured repo. | unset (feature off) |
| `QM_GITHUB_DEFAULT_ASSIGNEE` | No | Default assignee applied to created kit-gap issues. | unset |
| `QM_EMBEDDINGS_ENABLED` | No | Use local embeddings for `resolve_kits` trait/section inference. When off (or the dependency is absent) the server degrades to the deterministic lexical floor. | `true` |
| `QM_EMBEDDINGS_MODEL` | No | Embedding model id loaded by `fastembed`. | `BAAI/bge-small-en-v1.5` |
| `QM_EMBEDDINGS_CACHE_DIR` | No | Directory for model files + cached trait/section embeddings; put it on a writable volume to persist across restarts. | `/data/embeddings` (Docker image) |
| `QM_EMBEDDINGS_MIN_SCORE` | No | Minimum cosine similarity for an embedded trait/section to count. | `0.30` |
| `QM_EMBEDDINGS_TOP_K_PER_CATEGORY` | No | Max traits the embedding engine emits per category. | `4` |
| `QM_LLM_PROVIDER` | No | Optional LLM for `resolve_kits` trait inference: `openai` (OpenAI-compatible endpoint) or `anthropic`. Unset disables the LLM layer (embeddings/lexical still work). | unset (feature off) |
| `QM_LLM_BASE_URL` | No | Base URL for the OpenAI-compatible endpoint (Ollama/vLLM/llama.cpp/cloud). Required for `openai`. | unset |
| `QM_LLM_MODEL` | No | Model id passed to the configured LLM backend. Required when a provider is set. | unset |
| `QM_LLM_API_KEY` | No | API key/token for the LLM backend. Required for `anthropic`; optional for local `openai` servers. | unset |
| `QM_LLM_TIMEOUT_SECONDS` | No | Per-request LLM timeout; on timeout the resolver falls back to embeddings, then lexical. | `8.0` |
| `QM_DEV_AUTH_ENABLED` | No | **Dev only — never set in production.** Local auth bypass / token-minting routes. | `false` |
| `QM_DEV_SHARED_SECRET` | No | **Dev only — never set in production.** HS256 signing secret for dev tokens. | unset (HS256 rejected) |
| `QM_LOG_LEVEL` | No | Console log level when `QM_LOG_CONFIG` is unset. | `INFO` |
| `QM_LOG_CONFIG` | No | Path to a TOML `dictConfig` file for full logging control. | unset (colored console) |
| `QM_METRICS_PROMETHEUS_ENABLED` | No | Mount a Prometheus `GET /metrics` pull endpoint (needs the `telemetry` extra). OTLP push uses the standard `OTEL_*` env vars. See [OBSERVABILITY.md](OBSERVABILITY.md). | `false` |
| `QM_METRICS_ALLOW_ANONYMOUS` | No | Serve `/metrics` without auth. When false it requires app-token Basic (the `/dav` token); set true only when isolated at the network layer. | `false` |
| `QM_METRICS_SECTION_LEVEL` | No | Emit per-section delivery metrics (`qm.section.deliveries`); higher cardinality. | `false` |

\* `QM_KITS_ROOT` is optional only because the Docker image defaults it to
`/data/kits`; the server needs a kit catalog at that path to serve anything.

### Upgrading

Quartermaster keeps no database and runs no migrations. All persistent state
lives on the `/data` volume:

- the kit catalog, if you mount it there;
- `client_registry.json` (registered client User-Agents);
- `app_tokens.json` (hashed WebDAV app tokens).

To upgrade:

1. **Back up the `/data` volume** first (a plain copy of the directory is
   sufficient — it is just files).
2. Pull the new image tag — a channel (`:stable`, `:beta`, `:alpha`) or a
   pinned version — from `ghcr.io/exhuma/quartermaster`.
3. Recreate the container against the same `/data` volume, preserving it
   across the upgrade (do **not** delete or recreate the volume).

There are no data migrations to run; the new container reads the existing
state as-is.

---

## The kit catalog

Quartermaster serves a catalog of kits but does **not** contain one. The
catalog lives in its own repository and is supplied to the server via
`QM_KITS_ROOT`. You can author and edit kits in three ways:

- **Directly in the catalog repository** — kits are plain Markdown +
  `index.toml`/`applicability.json` files. Edits are visible to a running
  server immediately (kit reads are uncached).
- **Through the web UI** — kit CRUD over the `/api` admin API.
- **Over WebDAV** — mount the catalog as a network drive via the `/dav`
  endpoint and author kits with a coding agent.

Kits follow **semantic versioning**: the major version is encoded in the
directory structure (`v1/`, `v2/`, …); minor and patch changes are
recorded in each kit's `CHANGELOG.md` without creating a new folder. Use
`compare_kit_versions` via the MCP server to see what changed between two
versions and whether the change affects end-users.

For the full kit structure, metadata schema, and versioning rules, see
[`AUTHORING_KITS.md`](AUTHORING_KITS.md).

---

## AI assistant instructions

See [`.ai/rules.md`](.ai/rules.md) for rules that apply when AI coding
assistants work inside this repository.
