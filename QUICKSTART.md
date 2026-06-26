# Quickstart — run Quartermaster locally

Get the server **and** web UI running in a few minutes, with **no Keycloak**
and no external kit catalog, using the built-in dev-auth bypass. This is for
trying it out — for real authentication and deployment, see the
[README](README.md) and [DEVELOPMENT.md](DEVELOPMENT.md).

**You need:** Python with [`uv`](https://docs.astral.sh/uv/), and Node 22+ with npm.

---

## 1. Make a tiny kit catalog

The server serves kits from a directory (`QM_KITS_ROOT`); it isn't bundled with
one. Create a throwaway catalog with a single example kit so there's
something to see:

```bash
mkdir -p /tmp/qm-kits/hello-kit/v1/instructions

cat > /tmp/qm-kits/hello-kit/applicability.json <<'JSON'
{
  "kit_type": "module",
  "summary": "A minimal example kit for trying out Quartermaster.",
  "domains": ["example"], "languages": ["python"], "frameworks": [], "contexts": ["backend"],
  "requires": { "languages": [], "frameworks": [], "capabilities": [], "contexts": [] },
  "excludes": { "languages": [], "frameworks": [], "capabilities": [], "contexts": [] },
  "optional_signals": ["demo"], "related_kits": [], "priority": 10
}
JSON

cat > /tmp/qm-kits/hello-kit/CHANGELOG.md <<'MD'
# Changelog
## v1.0.0
- Initial example kit.
MD

cat > /tmp/qm-kits/hello-kit/v1/instructions/index.toml <<'TOML'
summary = "A minimal example kit demonstrating the section format."

[[sections]]
file = "invariant.md"
title = "Invariants"
gloss = "The one rule this example kit teaches."
always_load = true
TOML

cat > /tmp/qm-kits/hello-kit/v1/instructions/invariant.md <<'MD'
# Invariants
- This is a demo kit. Replace it with your own — see AUTHORING_KITS.md.
MD
```

(Authoring real kits: see [AUTHORING_KITS.md](AUTHORING_KITS.md).)

## 2. Start the backend (dev auth, no Keycloak)

```bash
cd server
uv sync
QM_DEV_AUTH_ENABLED=true \
QM_DEV_SHARED_SECRET=local-dev-secret \
QM_KEYCLOAK_URL=https://auth.example.com \
QM_KEYCLOAK_REALM=master \
QM_RESOURCE_BASE_URL=http://localhost:8000 \
QM_KITS_ROOT=/tmp/qm-kits \
uv run uvicorn app.main:app --reload
```

The `KEYCLOAK_*` values are placeholders — with dev auth, tokens are
self-signed locally and never checked against Keycloak. Verify it's up:

```bash
curl http://localhost:8000/health        # → {"status":"ok"}
```

## 3. Start the web UI (dev auth)

In a second terminal:

```bash
cd webui
npm install
echo 'VITE_DEV_AUTH=true' > .env
npm run dev                               # → http://localhost:5173
```

Open <http://localhost:5173>. You're auto-logged-in (no Keycloak), and the
kit list shows **hello-kit**. The Vite dev server proxies `/api` and `/kits`
to the backend, so it all looks like one origin.

That's it — Quartermaster is running.

---

## Connect a coding agent (optional)

Mint a dev token and point an MCP client at the server:

```bash
cd server
QM_DEV_AUTH_ENABLED=true QM_DEV_SHARED_SECRET=local-dev-secret \
QM_KEYCLOAK_URL=https://auth.example.com QM_KEYCLOAK_REALM=master \
QM_RESOURCE_BASE_URL=http://localhost:8000 QM_KITS_ROOT=/tmp/qm-kits \
uv run python -m app.dev_auth                     # prints a Bearer token
```

```bash
claude mcp add --transport http quartermaster \
  http://localhost:8000/kits/mcp \
  --header "Authorization: Bearer <paste-token>"
```

Then call `list_kits` / `get_kit` from the agent.

---

## Important caveats

- **Dev auth is local-only and insecure.** `QM_DEV_AUTH_ENABLED` /
  `QM_DEV_SHARED_SECRET` (and `VITE_DEV_AUTH`) must never be set in a deployed
  environment. They're off by default and stripped from production builds.
- **The published Docker image's UI needs real Keycloak.** The dev-auth
  bypass only works under the Vite dev server (`npm run dev`); it is
  dead-code-eliminated from production builds, including the GHCR image.
- **For real auth + deployment** (Keycloak setup, Docker + Traefik, GHCR
  image), follow the [README](README.md).
