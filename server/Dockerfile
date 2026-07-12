# syntax=docker/dockerfile:1.7-labs
# Build context is the repository ROOT — the releasable core is the server
# plus the built web UI. The kit catalog is intentionally NOT copied in (it
# is excluded by .dockerignore); supply it at runtime via a read/write
# volume at /data/kits (the default QM_KITS_ROOT). The image can therefore be
# published independently of any private kit content.
#
#   docker build -f server/Dockerfile . -t quartermaster
#
# Release builds should pass the git tag so the SPA and the API report the
# same version (frontend VITE_APP_VERSION + backend QM_APP_VERSION, both fed
# from this one arg):
#
#   docker build --build-arg APP_VERSION="$(git describe --tags)" \
#     -f server/Dockerfile . -t quartermaster

# Single release-version knob, mapped into both stages below. Unset in plain
# dev builds — the SPA hides the version chip and the API falls back to the
# installed package metadata.
ARG APP_VERSION=

# ---------------------------------------------------------------------------
# Stage 1 — web UI build
# ---------------------------------------------------------------------------
FROM node:22-slim AS frontend

WORKDIR /webui

# Install dependencies against the committed lockfile first (cached layer).
COPY webui/package.json webui/package-lock.json ./
RUN npm ci --no-audit --no-fund

# Build the static SPA. Runtime config is injected by the server at
# /config.js, so the build is environment-agnostic — EXCEPT build identity
# (repo link + commit + build time), which is necessarily baked at build time
# (module-github-link, module-release-metadata). Vite picks up VITE_* ARGs
# automatically; each is optional and its UI element is hidden when unset.
ARG VITE_GITHUB_REPO_URL
ARG VITE_APP_COMMIT
ARG VITE_APP_BUILD_TIME
# Map the global release knob into the Vite-exposed var so the SPA bakes it in.
ARG APP_VERSION
ENV VITE_APP_VERSION=$APP_VERSION
COPY webui/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2 — Python dependency installation
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast, reproducible dependency resolution.
RUN pip install --no-cache-dir uv==0.6.*

# Copy only the dependency manifests first so Docker can cache this layer
# independently of application code changes.
COPY server/pyproject.toml server/uv.lock ./

# Install production dependencies into an isolated virtual environment.
# UV_PROJECT_ENVIRONMENT must point to the final runtime path so script
# shebangs (e.g. uvicorn) embed the correct interpreter path.
ENV UV_PROJECT_ENVIRONMENT=/app/.venv
# Include the `embeddings` extra (local trait inference for `resolve_kits`) and
# the `telemetry` extra (OpenTelemetry metrics/traces + tiktoken token sizing).
# Both are optional at runtime — without them the server degrades gracefully
# (lexical floor; no-op telemetry with bytes/4 token estimates).
RUN uv sync --frozen --no-dev --no-install-project \
    --extra embeddings --extra telemetry

# Pre-seed tiktoken's cl100k_base vocabulary into a baked cache so token
# counting works offline (air-gapped installs). TIKTOKEN_CACHE_DIR points the
# runtime at the same path.
ENV TIKTOKEN_CACHE_DIR=/app/tiktoken_cache
RUN /app/.venv/bin/python -c \
    "import tiktoken; tiktoken.get_encoding('cl100k_base')"

# Pre-seed the embedding model (BAAI/bge-small-en-v1.5, ~130 MB ONNX) into a
# baked cache so the first `resolve_kits` call needs neither network egress nor
# a writable volume — eliminating the cold-start download that, if interrupted
# or blocked, silently degrades the resolver to its lexical floor. It is baked
# under /app and NOT /data on purpose: a runtime bind mount over /data would
# mask a volume-baked model. fastembed lays the files out under
# `<cache_dir>/models--…`; the runtime loads from `{QM_EMBEDDINGS_CACHE_DIR}/
# models`, so this build path and that runtime path must stay in sync.
RUN /app/.venv/bin/python -c \
    "from fastembed import TextEmbedding; \
     TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/app/embeddings/models')"

# Install the project package itself (after deps, to keep the uv sync layer
# cached). This creates the .dist-info so importlib.metadata.version("quartermaster")
# resolves correctly at runtime instead of falling back to "0.0.0".
# `uv pip` does not honour UV_PROJECT_ENVIRONMENT (that is for `uv sync`/`uv run`),
# so point it at the venv explicitly.
COPY server/app/ ./app/
RUN uv pip install --python /app/.venv/bin/python --no-deps .

# ---------------------------------------------------------------------------
# Stage 2b — documentation build
# ---------------------------------------------------------------------------
# Reuse the builder — it has the backend package + all deps in /app/.venv, so
# Sphinx autodoc can import ``app``. Add the build-only `docs` dependency group
# (Sphinx + furo + MyST) on top and render the site to static HTML.
FROM builder AS docs

# The docs tree lives at the repo root; its MyST includes reach the root-level
# CHANGELOG.md and contract.md, and conf.py reads server/pyproject.toml for the
# fallback version + imports ``app`` from the copied source. Bring them in.
COPY docs/ ./docs/
COPY CHANGELOG.md contract.md ./
COPY server/pyproject.toml ./server/pyproject.toml

# Add the Sphinx toolchain to the shared venv. Re-specify the extras so the
# sync does not prune them; --no-dev drops pytest/ruff/mypy/clproc.
RUN uv sync --frozen --no-install-project --no-dev \
    --extra embeddings --extra telemetry --group docs

# Stamp the release version into the docs (falls back to pyproject when unset),
# from the same single knob that feeds the SPA + API.
ARG APP_VERSION
ENV APP_VERSION=$APP_VERSION

# Zero-warning HTML build (-W), matching CI and the module-docs-sphinx kit.
RUN /app/.venv/bin/sphinx-build -W -b html docs docs/_build/html

# ---------------------------------------------------------------------------
# Stage 3 — runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS final

# Run as a non-root user for defence-in-depth. Give it a real home directory:
# libraries that cache under $HOME (notably huggingface_hub and its xet
# downloader, which write chunk caches + logs to ~/.cache/huggingface
# regardless of any explicit cache_dir) fail with EACCES when /home/appuser
# does not exist. A writable home keeps those paths from breaking.
RUN useradd --uid 1001 --create-home --shell /usr/sbin/nologin appuser

# Copy the pre-built virtual environment from the builder stage.
COPY --from=builder /app/.venv /app/.venv

# Copy the pre-seeded tiktoken vocabulary so token counting runs offline.
COPY --from=builder /app/tiktoken_cache /app/tiktoken_cache
ENV TIKTOKEN_CACHE_DIR=/app/tiktoken_cache

# Copy the pre-seeded embedding model so trait inference works offline with no
# cold-start download. Owned by appuser because the trait-embedding JSON caches
# (keyed by catalog fingerprint) are written into this same dir at runtime.
COPY --from=builder --chown=appuser:appuser /app/embeddings /app/embeddings

# Copy the application package, the built web UI, and the rendered docs site —
# no kit content.
COPY server/app/ /app/server/app/
COPY --from=frontend /webui/dist /app/server/webui_dist
COPY --from=docs /build/docs/_build/html /app/server/docs_dist

# The kit catalog is supplied at runtime via a mounted volume. Create the
# mount point and make /data writable by the non-root user so the WebDAV
# authoring endpoint (later phase) and the client registry can write there.
RUN mkdir -p /data/kits && chown -R appuser:appuser /data
ENV QM_KITS_ROOT=/data/kits
ENV QM_CLIENT_REGISTRY_PATH=/data/client_registry.json
ENV QM_APP_TOKENS_PATH=/data/app_tokens.json
# Local metrics store (in-app dashboard, independent of OTEL) on the /data
# volume so its rolling window survives container restarts.
ENV QM_METRICS_LOCAL_DB_PATH=/data/metrics.db
ENV QM_WEBUI_DIST=/app/server/webui_dist
# Rendered documentation site, served at /docs (app/docs_site.py).
ENV QM_DOCS_DIST=/app/server/docs_dist
# Embedding model + trait-embedding caches live under /app (baked into the
# image above), NOT on the /data volume — a runtime bind mount over /data would
# mask the baked model and reintroduce the cold-start download. The model is
# read-only; the trait-embedding JSON caches are written here at runtime (dir
# is appuser-owned via the COPY --chown above).
ENV QM_EMBEDDINGS_CACHE_DIR=/app/embeddings

WORKDIR /app/server

USER appuser

# Release version the API reports (service.version + X-Quartermaster-Version),
# from the same build arg that fed the SPA's VITE_APP_VERSION. Unset → the
# runtime falls back to the installed package metadata (see app/version.py).
ARG APP_VERSION
ENV QM_APP_VERSION=$APP_VERSION

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

VOLUME ["/data/kits"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
