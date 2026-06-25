# Contributing to Quartermaster

Thanks for your interest in contributing! Quartermaster is a self-hosted
MCP server (FastAPI + FastMCP backend, Vue 3 + Vuetify SPA) that serves AI
instruction kits to coding agents.

## Getting set up

See [`DEVELOPMENT.md`](DEVELOPMENT.md) for the full local setup. In short:

```bash
# Backend
cd server && uv sync
# Web UI
cd webui && npm install
```

Note the kit **catalog is not part of this repository** — point `KITS_ROOT`
at a local checkout of a kit catalog to run the server against real data.

## Before you open a pull request

Run the same checks CI runs:

```bash
# Backend
cd server && uv run pytest

# Web UI
cd webui && npm run test && npm run build && npm run check:no-dev-auth
```

All must pass. The `check:no-dev-auth` guard ensures the dev-only auth
bypass never leaks into a production bundle.

## Guidelines

- Keep changes focused; one logical change per PR.
- Match the surrounding code style and the 3-layer split in `server/app/`
  (routers → services → storage).
- Add or update tests for behavioural changes.
- Update `CHANGELOG.md` and relevant docs when user-facing behaviour changes.
- Never commit secrets. `server/.env` / `webui/.env` are git-ignored; commit
  only `.env.example` with placeholders.
- Pin any new third-party GitHub Action to a full commit SHA.

## Reporting security issues

Please do **not** file public issues for vulnerabilities — see
[`SECURITY.md`](SECURITY.md).
