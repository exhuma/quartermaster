# AGENTS.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Committing

GPG commit signing is unavailable in the Claude Code session — the signing
prompt cannot be answered and the commit hangs until it times out. Always
commit with signing disabled (e.g. `git -c commit.gpgsign=false commit ...`) so
commits succeed without waiting on GPG.

When quartermaster is available, treat its published trait vocabulary and
bootstrap guidance as the source of truth for kit discovery; normalize user
intent to supported traits before selection and retry when coverage is low.

## What this repository is

This repository is **Quartermaster** — a self-hosted **MCP server** (FastAPI + FastMCP) plus its Vue/Vuetify web UI. It exposes **AI instruction kits** over an authenticated HTTP endpoint, so agents load kits on demand without the kit files ever being copied into a target project repo.

**The kit catalog is *not* in this repository.** Kits are *content/data*, served from an external catalog supplied at runtime via `QM_KITS_ROOT` (a local checkout in dev, a mounted volume in production). Never add a `kits/` directory or an `instructions/` kit guide here — kit authoring lives in the separate kit-catalog repository. See `.ai/rules.md` for the authoritative rules for working in this repo.

**Intended usage** — kits are selected **per task** (or on any edit/planning aspect), not pinned once per project. Since tasks and traits evolve mid-conversation (e.g., adding login leading to OIDC), agents must trigger `resolve_kits` on the initial user-prompt, any subsequent change of scope/details, and when preparing/planning edits in the agent loop. Load lean: fetch required section contents via `get_kit` only once per session to save token space. Offering optional sections can occur sparingly multiple times. If context-clearing or compaction occurs in the agent session, the agent can re-fetch and re-deliver sections as needed. The server ships this workflow as the FastMCP `instructions` string (`MCP_INSTRUCTIONS` in `app/main.py`), surfaced to clients on connect.

## Server commands

All commands run from `server/`. The project uses `uv`.

```bash
cd server
uv sync                      # install deps (incl. dev group)
uv run pytest                # run all tests
uv run pytest tests/test_kits.py            # one test file
uv run pytest tests/test_kits.py::test_name # one test
uv run pytest -k <expr>                      # match by name

# Local dev server (QM_KEYCLOAK_URL/REALM/QM_RESOURCE_BASE_URL are required env vars)
QM_KEYCLOAK_URL=https://auth.example.com \
QM_KEYCLOAK_REALM=master \
QM_RESOURCE_BASE_URL=http://localhost:8000 \
uv run uvicorn app.main:app --reload
```

`pyproject.toml` sets `pythonpath = ["."]`, so tests and `uvicorn` import `app.*` directly from `server/`.

Docker builds use the **repo root as the build context** — the core image is the server **plus the built web UI** (a `node` stage builds `webui/`). The kit catalog is **not** baked in: `.dockerignore` excludes `kits/`. Supply the catalog at runtime by mounting a volume at `/data/kits` (the default `QM_KITS_ROOT`); writes to it are visible to the MCP immediately (kit reads are uncached), with no restart.

```bash
docker build -f server/Dockerfile . -t quartermaster
# run with an external kit catalog mounted (the catalog is NOT part of this repo):
docker run -e QM_KITS_ROOT=/data/kits -v "/path/to/your/kit-catalog:/data/kits" ... quartermaster
```

## Server architecture

Request flow: `Traefik (TLS only, no auth) → FastAPI → JWTAuthMiddleware → /kits/mcp` (FastMCP streamable-HTTP). **Auth terminates inside the application**, not at the proxy.

- **`app/main.py`** — the outer FastAPI app, assembled by a `create_app()` application factory (`app = create_app()` at module level for uvicorn). Defines every `@mcp.tool` (thin wrappers that translate domain exceptions into `ValueError` for MCP), mounts the FastMCP app at `/kits/mcp`, serves public unauthenticated endpoints (`/health`, RFC 9728 `/.well-known/oauth-protected-resource`, RFC 8414 `/.well-known/oauth-authorization-server`), and adds `JWTAuthMiddleware` last so it wraps everything. The factory is where later phases register the `/api` admin routers and the `/dav` WebDAV mount. The well-known docs let OAuth-aware clients (e.g. VS Code) discover Keycloak and run a PKCE flow automatically. Note: tools are mounted under `/kits/mcp`, not `/mcp` as some README snippets show.
- **`app/auth.py`** — `JWTAuthMiddleware`. Validates Keycloak RS256/ES256 bearer JWTs against the realm JWKS (cached 1h, auto-rotates). Paths in `_PUBLIC_PATHS` and anything under `/.well-known/` skip auth. Optional `QM_COPILOT_AUTH_ENABLED` mode accepts `X-Client-Id`/`X-Client-Secret` headers, validated live against the Keycloak token endpoint via `client_credentials`. The middleware only checks cryptographic validity + issuer (+ optional audience); it does **not** inspect roles/scopes. Per-collaborator isolation is a Keycloak concern (one service-account client each).
- **Dev auth bypass** (`app/dev_auth.py`, `app/routers/auth_dev.py`, `module-dev-auth-bypass`) — lets the app run locally without an IdP, **inert in production**. `_select_token_validation_mode` routes by the unverified `alg` header: HS256 → dev-secret validator *only* when `QM_DEV_SHARED_SECRET` is set (else rejected), RS256/ES256 → JWKS, anything else rejected. Dev tokens carry the same `iss`/`aud`. The `/auth/dev/token` minting router mounts **only** when `QM_DEV_AUTH_ENABLED` (a plain 404 otherwise). Frontend half (`webui/src/auth/devAuth.ts`, gated by `config.devAuth = import.meta.env.DEV && VITE_DEV_AUTH==='true'`) is tree-shaken from production builds (guarded by `npm run check:no-dev-auth`). Both env flags must be unset in production.
- **`app/config.py`** — `Settings` (pydantic-settings, env-driven, `.env` supported), exposed as an `lru_cache` singleton via `get_settings()`. `kits_root` is **required** (`QM_KITS_ROOT`) and points at an external kit catalog — a local checkout in dev, the externally-mounted volume in production; the catalog is never bundled with this server. Computes all Keycloak/OAuth URLs from `keycloak_url` + `keycloak_realm` + `resource_base_url`.
- **`app/kits.py`** — kit discovery and the **V2 trait-based selector** (the bulk of the logic). Scans `kits/*/v*/instructions/index.toml` for kits and `kits/<name>/applicability.json` for ranking manifests. `_load_kit_index` parses the per-kit `index.toml` (via stdlib `tomllib`); `read_kit_outline` returns the cheap section map; `read_kit(name, version, sections)` returns either the full concatenation or only the requested sections. `select_kits_v2` / `explain_kit_v2` score kits against project traits (languages/frameworks/capabilities/contexts) using `requires`/`excludes`/`priority`. `compare_kit_versions` parses `kits/<name>/CHANGELOG.md` and flags end-user-facing changes via a keyword regex.
- **`app/routers/`** — thin HTTP routing layer (module-fastapi 3-layer). `kits_admin.py` is the REST kit-CRUD API under `/api/kits` (noun URLs, no version segment, idempotent PUT/DELETE); `integration.py` serves `GET /api/integration` (MCP URL + Keycloak/OAuth discovery for the web UI); `clients.py` is the client-registration API (`/api/clients`). All `/api` routers require the vendor `Accept` type and emit `VendorJSONResponse` (see below). Routers hold no logic and let domain exceptions propagate; `create_app` maps them to HTTP status codes (404/409/422/400).
- **`app/media_types.py`** — the vendor media type (`application/vnd.instructions+json; v=1`). `require_vendor_accept` is a router dependency that returns **406** for bare `application/json`/`*/*` (strict negotiation, per module-api-design); `VendorJSONResponse` stamps the vendor `Content-Type` on every `/api` response. Swagger (`/docs`, `/openapi.json`) is enabled so the contract is discoverable (still behind auth).
- **`app/user_agent.py`** — `UserAgentMiddleware`. Identifies clients by `User-Agent`: browsers (`Mozilla/…`) pass by default; non-browser clients must register their UA (else **403** pointing to `/api/clients`). Covers **only the REST API** (`/api`) — the MCP mount, health, well-known docs, and Swagger are exempt, as is the `POST /api/clients` bootstrap. Identification aid, not a strong gate. Registry persisted by `app/storage/client_registry.py` (file-backed, atomic), path from `client_registry_path` settings.
- **`app/services/kit_service.py`** — kit-CRUD business logic with **validate-before-commit**: every mutation stages the proposed end-state, validates it via the existing loaders (`_load_kit_index`, `_validate_manifest`), and only then atomically swaps it into place, so a bad write can never leave the catalog unloadable. New domain exceptions `KitConflictError` (409) / `KitValidationError` (422) live in `app/kits.py` with the `KitNotFoundError` family.
- **`app/eval/`** — in-process, **domain-agnostic** **catalog-evaluation** of kit resolution quality, for kit authors (`app/eval/README.md`; author guide `docs/user/evaluating-kits.md`). The active kit root *is* the catalog, so it evaluates not-yet-deployed kits in any domain (baking, legal, software — the kits define the domain); nothing domain-specific ships. Corpus (`corpus.py`): one auto-probe per kit from its manifest (`requires` = should-infer, `excludes` = must-not-infer) plus an OPTIONAL author-supplied `eval-cases.yaml` discovered at the catalog root (`load_author_cases`); case sets are `catalog|authored|all`. `runner.py` reproduces the *real* `_infer` + `select_kits_v2` path but **bypasses the `resolve_kits` wrapper** so the memory nudge and metrics attribution never fire (a batch eval has no caller). `report.py` (pure) scores records into per-case verdicts, a **catalog-wide false-exclusion tally** (kits an over-inferred trait silently drops), **cross-kit interference** (`self_probe_displacement` → which kit out-ranks another on its own probe), per-category **trait contamination**, and `diff_reports` (before/after regression of a kit edit). Each record carries the `engine` that ran, so a silent degrade to the lexical floor shows up as `engine_drift`. Four surfaces: the `python -m app.eval` CLI (local, no server; `--kits-root`/`--baseline`; standalone-safe placeholder settings; CI-gate exit code); the sync `evaluate_catalog` MCP tool (one call → report over the instance's own catalog, run via `anyio.to_thread`); the domain-neutral `catalog_evaluation` MCP prompt (runbook for an author's agent); and the async REST job — `app/services/eval_service.py` owns a process-local in-memory background-job store (`app/eval/jobs.py`, single-process) and `app/routers/eval.py` serves `POST /api/eval/resolution` (202 + job id) / `GET /api/eval/resolution/{id}` (poll → report), `EvalJobNotFoundError` → 404.
- **`app/storage/kit_writes.py`** — the filesystem write half of storage: atomic writes (`os.replace`), atomic directory swaps, idempotent deletes, and path-confinement (`resolve_within`, name/version/section validators raising `KitPathError`). No business logic.
- **`app/dav/webdav_app.py`** — embedded WebDAV authoring endpoint at `/dav` (wsgidav `FilesystemProvider` over `kits_root`, bridged to ASGI by `a2wsgi`). Lets users mount the catalog as a drive and author kits with a coding agent; writes land on `kits_root` and are visible to the MCP immediately (uncached reads). wsgidav runs **anonymous** — auth is enforced upstream: `JWTAuthMiddleware` handles `/dav` via HTTP **Basic `username:app-token`** (OS mount clients can't run an OIDC browser flow), refuses Basic over non-TLS (`dav_require_tls`), and emits a `Basic` `WWW-Authenticate`. App tokens are server-issued opaque secrets stored hashed and bound to the minting OIDC user (`app/storage/app_tokens.py`), minted/listed/revoked via `/api/app-tokens` (`app/routers/app_tokens.py`); the middleware sets `request.state.auth_subject` so those routes know the caller.
- **`app/webui.py`** — serves the built SPA and a runtime `/config.js` (`window.__APP_CONFIG__` rendered from settings: Keycloak authority, public client id, redirect URIs, same-origin api base — public values only). `mount_webui` adds `/assets` (StaticFiles), `/config.js`, `/`, and an SPA history-mode fallback that excludes `/api`+`/kits` so unknown ones still 404; no-op when there is no build. **Auth model**: `app/auth.py` now protects only `/api`+`/kits` (`_requires_auth`); the SPA shell, `/config.js`, well-known and Swagger docs are public (the SPA is static JS that authenticates via OIDC before any token exists).
- **`webui/`** — the Vue 3 + Vuetify 4 SPA (npm, Vite, vitest), following `module-vue-vuetify` / `module-runtime-config-spa` / `module-auth-oidc-vue`. `src/api/index.ts` is the central fetch seam (`ApiError`, `TokenProvider`/`setTokenProvider`, `setUnauthorizedHandler`, vendor `Accept`/`Content-Type`); `src/config.ts` is the only reader of `window.__APP_CONFIG__`/`import.meta.env` (runtime wins, VITE_* dev fallback, fail-loudly at boot); `src/auth/oidc.ts` is the oidc-client-ts PKCE client; singleton composables (`useAuth`/`useKits`/`useIntegration`/`useLoading`); views `KitListView`, `IntegrationView` (per-client MCP setup + UA registration), `AuthCallbackView`. Built into the image at `QM_WEBUI_DIST`.
- **`app/prompts.py`** — static canned MCP prompt templates.
- **`app/notifications/`** — pluggable maintainer-notification backends for kit-extension/gap requests: `base.py` defines the `IssueBackend` Protocol (`find_existing`/`create`) plus shared `GapReport`/`IssueRef` types and dedupe/formatting helpers; `github.py` and `gitlab.py` implement it; `__init__.py` selects the backend via `QM_ISSUE_BACKEND` (`github`/`gitlab`/`none`, defaulting to `github` when only `GITHUB_*` settings are set) and exposes the orchestration seam (`request_kit_extension`, `check_existing_kit_extension_issue`, `gap_tools_enabled`). `app/requests.py` is now a thin backward-compatible re-export.
- **`app/gap.py`** — catalog-recall gap detection: when trait inference finds nothing for a task, `detect_gap` runs a fuzzy pass (embedding cosine similarity, or lexical word-overlap when no embedder is available) over every trait pseudo-document before reporting a genuine catalog gap — a real (if fuzzy) match means the miss was in wording/inference, not coverage, so it is *not* a gap. Never touches `select_kits_v2`'s own thresholds. Gated by `QM_GAP_DETECTION_ENABLED`.
- **`app/resolver.py`** — the **one-shot `resolve_kits` pipeline**: a free-text task in → ranked kits with `always_load` content inlined out, collapsing the manual discovery loop into one call to save client/premium context. Infers the four trait lists via a fallback chain (LLM → embeddings → lexical floor), feeds them to the **unchanged** `select_kits_v2`, applies a bounded per-user memory nudge (see `app/personalization.py`), runs catalog-recall gap detection when inference found nothing, then ranks sections with the winning engine and assembles a hybrid response (`always_load_markdown` inlined + `fetch_on_demand` ids for the existing `get_kit`, plus a nullable `gap` block). The `LexicalTraitEngine` floor needs no config and never hard-fails; `_build_trait_engines` prepends the optional engines when configured (settings access is `ValidationError`-tolerant, so an unconfigured env just uses lexical). Also attributes each resolve to the authenticated caller (`current_sub()`) and its inferred traits into the local metrics store, feeding per-user memory derivation.
- **`app/personalization.py`** — bounded, familiarity-based ranking nudge: `apply_memory_nudge` re-sorts (never filters) `select_kits_v2` candidates using a per-caller memory profile, capped at `MEMORY_BONUS_CAP = 8` — strictly below the smallest real trait weight (`WEIGHT_CONTEXTS = 10` in `app/kits.py`) — so a genuine trait match always outranks mere familiarity (no "tunnel vision"). `profile_hint` renders a short, kit-name-free advisory line injected into the sampling/LLM prompt.
- **`app/storage/user_memory.py`** — the per-user memory store: a small, capped, TOML profile (top domains/kits/languages/frameworks) derived from a subject's own resolve history via `derive_profile` (exponential recency decay, deterministic top-N, no LLM cost), lazily rebuilt by `get_or_build` when missing/stale. A disposable derived cache, not a source of truth — safe to delete. Viewable/resettable via the `get_my_memory`/`reset_my_memory` MCP tools or `GET`/`DELETE /api/me/memory`. Gated by `QM_USER_MEMORY_ENABLED`.
- **`app/traits.py`** — derives, from the same manifests `select_kits_v2` loads, the legal trait **vocabulary** and a per-trait **pseudo-document** (token + aggregated kit `summary`/`domains`/`optional_signals`) used to match a task to traits, plus `SectionRef`s for section ranking and a `catalog_fingerprint()` for cache keying. Adds the additive public `iter_catalog()` accessor to `app/kits.py`.
- **`app/embeddings.py`** — the deterministic embedding engine (the default baseline): lazy `fastembed` (ONNX, no torch) behind an `Embedder` Protocol; `get_embedder` returns `None` (→ degrade to lexical) when the `embeddings` extra/model is unavailable; trait-document embeddings are cached on disk keyed by model id + `catalog_fingerprint()`. Optional dependency (`pip install '.[embeddings]'`); the Docker image bundles it.
- **`app/llm.py`** — the optional pluggable LLM layer behind an `LLMBackend` Protocol: `OpenAICompatBackend` (Ollama/vLLM/llama.cpp/cloud) and `AnthropicBackend`, selected by `QM_LLM_PROVIDER`. Constrains output to the closed vocabulary (intersects the model's JSON with `vocab`), maps every failure to `LLMError` so the engine returns `None` and the resolver falls back; section ranking is delegated to the cheaper deterministic ranker so a resolve costs at most one LLM call.

The MCP tools are intentionally layered: `list_kits` → `list_available_traits` / `select_kits` → `explain_kit_candidate` → `get_kit_outline` → `get_kit` (optionally section-scoped via `sections=[…]`), with `check_existing_gap_issue` / `request_clarification_or_addition` for gaps and `get_my_memory` / `reset_my_memory` for per-user memory. `resolve_kits` is the one-shot fast path over that chain (free-text task → recommendation + inlined core content, plus catalog-recall gap detection and a bounded personalization nudge), backed by `app/resolver.py`.

## Kit catalog format (what the server parses)

Kits are authored in the **external catalog repo**, not here — but the server
discovers, parses, and validates this layout (see `app/kits.py`), so changes to
the parser/validator must stay consistent with it. The catalog (`QM_KITS_ROOT`) holds:

```
<kit-name>/
  applicability.json     ← V2 selector manifest (required, validated by app/kits.py)
  CHANGELOG.md           ← full version history (all major/minor/patch) (required)
  v1/                    ← major version folder; only majors get a folder
    instructions/        ← agent-facing adoption guide (required — the primary content)
      index.toml         ← section manifest: summary + ordered [[sections]]
      invariant.md       ← always-load core (invariants / prohibited patterns)
      <section>.md       ← one Markdown file per logical section
    README.md            ← doubles as a project-doc template for adopters
    workflows/           ← GitHub Actions templates, if any
    scripts/             ← supporting scripts, if any
  v2/ ...                ← created only on a breaking change
```

**Instruction sections**: `index.toml` has a `summary` and an ordered `[[sections]]` array; each section needs `file` (a `.md` basename), `title`, `gloss` (one-line outline text), and `always_load` (bool). The section id used by `get_kit(sections=[…])` is the file stem. `gloss`/`summary` are purpose-written, self-contained descriptions — never a hard cut of the section body: no trailing `…`, no mid-sentence/mid-bullet fragments, no bare `Overview` placeholders. Keep a `gloss` to one line (≤ ~100 chars) and a `summary` to one sentence (≤ ~150 chars). Front-load invariants/prohibited-patterns into `always_load = true` sections; isolate heavy code templates into their own sections. Reorganising sections is a minor/patch change, not a new `v<N>/`.

**Versioning** (semantic): only major versions get a `v<N>/` folder; minor/patch changes are `CHANGELOG.md` entries only. Changelog headings must match `## v<version>` for `compare_kit_versions` to parse them.

**`applicability.json`** must include all of: `kit_type` (`module`|`stack`|`release`), `summary`, `domains`, `languages`, `frameworks`, `contexts`, `requires`, `excludes`, `optional_signals`, `related_kits`, `priority` (int). `requires`/`excludes` are objects keyed by the four trait categories (`languages`, `frameworks`, `capabilities`, `contexts`). Missing or malformed manifests raise at load time. The kit-CRUD service (`app/services/kit_service.py`) validates these invariants before committing any write, so the catalog can never be left unloadable.
