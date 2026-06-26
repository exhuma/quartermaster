# AI Assistant Rules

This repository is **Quartermaster** — a self-hosted MCP server (plus its
web UI) that serves AI instruction kits to coding agents over an
authenticated HTTP endpoint. Its consumers are humans running and
deploying the server, and coding agents working on the server code.

**The kit catalog is not in this repository.** Kits are *data*, served
from an external catalog supplied at runtime via `QM_KITS_ROOT` (a local
checkout in dev, a mounted volume in production). Do **not** add a `kits/`
directory or any `instructions/` kit guide here — kit authoring belongs in
the separate kit-catalog repository, under its own rules.

## Structure

```
server/               ← FastAPI + FastMCP backend (the MCP server)
  app/                ← application code (3-layer: routers → services → storage)
  tests/              ← pytest suite
  Dockerfile
  docker-compose.yml
  pyproject.toml
webui/                ← Vue 3 + Vuetify single-page app (npm, Vite, vitest)
```

## Working on the server

All commands run from `server/` (the project uses `uv`):

```bash
uv sync                      # install deps (incl. dev group)
uv run pytest                # run all tests
```

Web UI commands run from `webui/` (npm):

```bash
npm install
npm run test                 # vitest
npm run build                # type-check + production build
npm run check:no-dev-auth    # guard: no dev-auth code in the production bundle
```

- The dev-auth bypass (`QM_DEV_AUTH_ENABLED` / `QM_DEV_SHARED_SECRET`, and the
  frontend `VITE_DEV_AUTH`) is **dev-only** and must stay inert in
  production. Never commit a `QM_DEV_SHARED_SECRET` value.
- `QM_KITS_ROOT` is required — there is no in-repo fallback catalog. Tests
  that need a real catalog skip cleanly when one is absent.
- See [`CLAUDE.md`](../CLAUDE.md) for the detailed server architecture.

## Non-negotiable rules

- **Never bundle a kit catalog into this repository or the Docker image.**
  The catalog is external; `.dockerignore` excludes any `kits/` checkout.
- Keep secrets out of the repository. `server/.env` / `webui/.env` are
  git-ignored; commit only `.env.example` with placeholder values.
- Follow the existing 3-layer split in `server/app/` (thin routers →
  services with business logic → storage); domain exceptions propagate and
  are mapped to HTTP status codes in `create_app`.
- Run `uv run pytest` (backend) and `npm run test && npm run build`
  (web UI) before proposing changes as complete.
