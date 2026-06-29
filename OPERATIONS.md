# Operations manual

How to run the Quartermaster container in production: image, ports,
environment variables, the volume **mounts** that matter, and a staged
rollout of the server-side inference for `resolve_kits` — **local embeddings
first, then an external LLM**.

For the authoritative, exhaustive list of every setting see the
[Configuration reference](README.md#configuration-reference). This document is
the operational view: what to mount, what to set, and how to verify.

---

## 1. What you are running

- A single image: the FastAPI + FastMCP server **plus** the built web UI.
  Pull `ghcr.io/exhuma/quartermaster` (channels `:stable`/`:beta`/`:alpha`,
  or a pinned version) or build it: `docker build -f server/Dockerfile . -t quartermaster`.
- Listens on **port 8000** (HTTP). Put TLS in front of it (Traefik, nginx,
  a cloud LB). **Auth terminates inside the app** (Keycloak JWT), not at the
  proxy — the proxy only needs to terminate TLS and route the host.
- The **kit catalog is not baked into the image.** You supply it at runtime
  as a mount (see §3).
- Runs as a non-root user (`appuser`, uid 1001). Everything it writes lives
  under `/data`, which must be writable by that uid.

Health probes (all unauthenticated):

| Path | Meaning |
|---|---|
| `GET /livez` (alias `GET /health`) | process is up |
| `GET /readyz` | the kit catalog is present and loadable |
| `GET /healthz` | full health, including Keycloak reachability |

The MCP endpoint is served (authenticated) at `/kits/mcp`.

---

## 2. Required environment variables

These four are mandatory; the server will not start without them:

| Variable | Example | Notes |
|---|---|---|
| `QM_KEYCLOAK_URL` | `https://auth.example.com` | Base URL of Keycloak, no trailing slash. |
| `QM_KEYCLOAK_REALM` | `quartermaster` | Realm that issues tokens. |
| `QM_RESOURCE_BASE_URL` | `https://qm.example.com` | Public origin (scheme + host) as the browser/agent reaches it. Drives OAuth metadata and SPA redirect URIs. |
| `QM_KITS_ROOT` | `/data/kits` | Path to the mounted catalog. Defaulted to `/data/kits` **in the image**, so in practice you only mount the volume. |

Everything else is optional and has a safe default. The inference settings
are covered in §4–§5.

---

## 3. Mounts (the important part)

The image keeps **all mutable state under `/data`**. Mount what you need to
persist; `/data` itself must be writable by uid 1001.

| Container path | What it is | Persist? | Default |
|---|---|---|---|
| `/data/kits` | **The kit catalog.** Bind-mount your own (possibly private) catalog checkout here. Writes via the `/dav` WebDAV endpoint land here and are visible to the MCP immediately — no restart. | **Required** | `QM_KITS_ROOT=/data/kits` |
| `/data/client_registry.json` | Registered non-browser client User-Agents. | Recommended | `QM_CLIENT_REGISTRY_PATH` |
| `/data/app_tokens.json` | Hashed WebDAV app tokens. | Recommended (if you use `/dav`) | `QM_APP_TOKENS_PATH` |
| `/data/logging.toml` | Optional `dictConfig` logging file, if you set `QM_LOG_CONFIG`. | Optional | unset |

A simple, durable layout is to mount **one named volume at `/data`** (so the
catalog and the small JSON state files persist together) and, if your catalog
lives elsewhere, bind-mount it over `/data/kits`:

```bash
docker volume create qm-data
docker run -d --name quartermaster -p 8000:8000 \
  -e QM_KEYCLOAK_URL=https://auth.example.com \
  -e QM_KEYCLOAK_REALM=quartermaster \
  -e QM_RESOURCE_BASE_URL=https://qm.example.com \
  -v qm-data:/data \
  -v /srv/kit-catalog:/data/kits \
  ghcr.io/exhuma/quartermaster:stable
```

> The bind-mount over `/data/kits` shadows that subpath of the named volume —
> intentional, so your catalog is managed separately from generated state.
> Ensure both are writable by uid 1001 (`chown -R 1001:1001 /srv/kit-catalog`
> for the bind mount).

---

## 4. Stage 1 — deterministic inference with local embeddings

This is the recommended first deployment of the new `resolve_kits` tool: a
**local embedding model**, no external services, fully self-hosted. It is on
by default and needs no setup — the model is baked into the image.

> Requires an image built with the `embeddings` extra (this feature version or
> newer — the stock `server/Dockerfile` includes it **and bakes the embedding
> model into the image at build time**, so first use needs no network egress
> and no writable cache volume). On an image without it, the server silently
> degrades to the lexical floor; rebuild from this repo
> (`docker build -f server/Dockerfile . -t quartermaster`) or pull a version
> that ships it.

### Settings

| Variable | Default | Set it if… |
|---|---|---|
| `QM_EMBEDDINGS_ENABLED` | `true` | leave as-is to use embeddings; `false` forces the lexical floor. |
| `QM_EMBEDDINGS_MODEL` | `BAAI/bge-small-en-v1.5` | you want a different `fastembed`-supported model. |
| `QM_EMBEDDINGS_CACHE_DIR` | `/app/embeddings` | you relocate the baked model / trait-embedding cache. Keep it off the `/data` volume — a bind mount there masks the baked model. |
| `QM_EMBEDDINGS_MIN_SCORE` | `0.30` | tune recall/precision of inferred traits. |
| `QM_EMBEDDINGS_TOP_K_PER_CATEGORY` | `4` | cap traits emitted per category. |

No LLM variables are set, so the inference chain is **embeddings → lexical**.

### Run

```bash
docker run -d --name quartermaster -p 8000:8000 \
  -e QM_KEYCLOAK_URL=https://auth.example.com \
  -e QM_KEYCLOAK_REALM=quartermaster \
  -e QM_RESOURCE_BASE_URL=https://qm.example.com \
  -v qm-data:/data \
  -v /srv/kit-catalog:/data/kits \
  ghcr.io/exhuma/quartermaster:stable
# embeddings are on by default; the model is baked into the image, so the first
# resolve_kits call needs no download and no extra mount.
```

### Verify it is using embeddings

Call `resolve_kits` from an authenticated MCP client (your coding agent, or
VS Code once OAuth discovery has run) with a task like *"add a FastAPI REST
endpoint"* and inspect the response: the top-level **`engine`** field reports
which layer answered.

```jsonc
{
  "engine": "embedding",          // <- local embeddings are active
  "inferred_traits": { "frameworks": ["fastapi"], ... },
  "kits": [ { "name": "...", "always_load_markdown": "…", "fetch_on_demand": ["…"] } ]
}
```

Operational signals:

- The model is baked into the image at `/app/embeddings/models/`; no download
  happens at runtime, so this works on air-gapped hosts out of the box.
- `engine: "lexical"` instead of `"embedding"` means embeddings did **not**
  run. Check the logs for `embeddings unavailable, degrading: …` and
  `trait engine 'embedding' failed: …` (the latter names the underlying
  exception — e.g. a relocated `QM_EMBEDDINGS_CACHE_DIR` that no longer
  contains the baked model, or an unwritable cache dir). The server still
  works — it has degraded to the deterministic lexical floor — but you are not
  getting semantic matching.

> **No cold start:** the embedding model ships inside the image, so the first
> `resolve_kits` after a fresh deploy only pays the in-process model *load*, not
> a download. Do not point `QM_EMBEDDINGS_CACHE_DIR` at the `/data` volume — a
> bind mount there masks the baked model and reintroduces a download.

---

## 5. Stage 2 — add an external LLM

Once embeddings are working, layer an LLM **in front** of them for the fuzzy
task→trait step. The chain becomes **LLM → embeddings → lexical**: if the LLM
times out, errors, or returns nothing in-vocabulary, the server falls back
automatically — so adding an LLM never makes resolution fail, it only sharpens
it. Section ranking still uses the (cheaper) embedding engine, so a resolve
costs **at most one LLM call**.

The LLM layer is **off** until you set a provider and its required fields.

### Option A — OpenAI-compatible endpoint (Ollama / vLLM / llama.cpp / cloud)

| Variable | Required | Example |
|---|---|---|
| `QM_LLM_PROVIDER` | yes | `openai` |
| `QM_LLM_BASE_URL` | yes | `http://ollama:11434/v1` |
| `QM_LLM_MODEL` | yes | `llama3.1` |
| `QM_LLM_API_KEY` | for cloud | `sk-…` (omit for a local server that needs no key) |
| `QM_LLM_TIMEOUT_SECONDS` | no | `8.0` |

```bash
docker run -d --name quartermaster -p 8000:8000 \
  -e QM_KEYCLOAK_URL=https://auth.example.com \
  -e QM_KEYCLOAK_REALM=quartermaster \
  -e QM_RESOURCE_BASE_URL=https://qm.example.com \
  -e QM_LLM_PROVIDER=openai \
  -e QM_LLM_BASE_URL=http://ollama:11434/v1 \
  -e QM_LLM_MODEL=llama3.1 \
  -v qm-data:/data \
  -v /srv/kit-catalog:/data/kits \
  ghcr.io/exhuma/quartermaster:stable
```

> If the LLM runs in another container, make sure both are on the same Docker
> network so `QM_LLM_BASE_URL` resolves (e.g. `--network my-net` and use the
> service name as the host).

### Option B — Anthropic-native

| Variable | Required | Example |
|---|---|---|
| `QM_LLM_PROVIDER` | yes | `anthropic` |
| `QM_LLM_API_KEY` | yes | `sk-ant-…` |
| `QM_LLM_MODEL` | yes | `claude-haiku-4-5-20251001` |
| `QM_LLM_TIMEOUT_SECONDS` | no | `8.0` |

A small, fast model (e.g. Claude Haiku) is the right pick here: trait
extraction is a short, constrained classification task, and using a cheap
model keeps the whole point — reducing token spend — intact.

### Verify the LLM is active

Call `resolve_kits` again and check the `engine` field:

- `engine: "llm"` → the LLM produced the traits.
- `engine: "embedding"` (or `"lexical"`) → the LLM was skipped or fell back.
  Grep the logs for `LLM inference failed: …` (network/timeout/bad output) or
  confirm the provider/model variables are all set. Resolution still succeeds
  via the lower layers.

---

## 6. Compose

The repo ships [`server/docker-compose.yml`](server/docker-compose.yml) for a
Traefik v3 front end. To enable the inference stages, add the relevant
variables to your `.env` (copy from
[`server/.env.example`](server/.env.example), which has an annotated
*"server-side inference"* section):

```yaml
services:
  quartermaster:
    # …existing config…
    volumes:
      - /srv/kit-catalog:/data/kits   # your catalog (existing)
      - qm-data:/data                 # persists the small JSON state files
    # Stage 1 needs nothing extra (embeddings on by default; model is baked in).
    # Stage 2: set QM_LLM_* in .env to turn on the LLM layer.

volumes:
  qm-data:
```

---

## 7. Quick reference: which engine, and why

| `engine` in the response | Meaning | If unexpected, check |
|---|---|---|
| `llm` | LLM mapped the task to traits | — |
| `embedding` | local embeddings did | `QM_LLM_PROVIDER` set? logs for `LLM inference failed` |
| `lexical` | the always-on floor did | logs for `embeddings unavailable, degrading`; cache dir writable? |

The fallback order is always **LLM → embeddings → lexical**; the first layer
that yields any in-vocabulary trait wins. The lexical floor needs no
configuration and never fails, so `resolve_kits` always returns a result.

---

## 8. Notes

- **Image size:** the embedding stack (`fastembed` + ONNX runtime + model)
  adds a few hundred MB — far lighter than a torch-based stack. For a
  minimal, lexical-only footprint set `QM_EMBEDDINGS_ENABLED=false`.
- **Determinism:** embedding results are reproducible on identical hardware;
  tiny floating-point differences across CPU microarchitectures can reorder
  near-ties, which a stable tie-break and `QM_EMBEDDINGS_MIN_SCORE` margin
  absorb.
- **Cache invalidation is automatic:** the embedding cache is keyed by the
  model id and a fingerprint of the catalog, so editing a kit (including via
  `/dav`) transparently rebuilds the affected embeddings on the next call.
- **No outbound calls unless you ask for them:** with `QM_LLM_PROVIDER` unset
  and the model pre-seeded, the server makes no inference-related network
  calls — suitable for air-gapped installs.

---

## 9. Observability (metrics + traces)

Quartermaster can emit OpenTelemetry **metrics and traces** that measure how
much kit content it delivers, which kits/sections get used, and how the catalog
grows over time. Push to any OTLP collector via the standard `OTEL_*` env vars,
or scrape Prometheus via `QM_METRICS_PROMETHEUS_ENABLED` (auth: app-token Basic
by default, or `QM_METRICS_ALLOW_ANONYMOUS` behind network isolation). With
nothing configured the layer is inert.

See **[OBSERVABILITY.md](OBSERVABILITY.md)** for the full metric reference, KPI
recipes (PromQL), a suggested Grafana dashboard, and the trace span tree.
