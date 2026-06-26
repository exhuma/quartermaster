# syntax=docker/dockerfile:1.7-labs
# Build context is the repository ROOT — the releasable core is the server
# plus the built web UI. The kit catalog is intentionally NOT copied in (it
# is excluded by .dockerignore); supply it at runtime via a read/write
# volume at /data/kits (the default QM_KITS_ROOT). The image can therefore be
# published independently of any private kit content.
#
#   docker build -f server/Dockerfile . -t quartermaster

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
RUN uv sync --frozen --no-dev --no-install-project

# ---------------------------------------------------------------------------
# Stage 3 — runtime image
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS final

# Run as a non-root user for defence-in-depth.
RUN useradd --uid 1001 --no-create-home --shell /usr/sbin/nologin appuser

# Copy the pre-built virtual environment from the builder stage.
COPY --from=builder /app/.venv /app/.venv

# Copy the application package and the built web UI — no kit content.
COPY server/app/ /app/server/app/
COPY --from=frontend /webui/dist /app/server/webui_dist

# The kit catalog is supplied at runtime via a mounted volume. Create the
# mount point and make /data writable by the non-root user so the WebDAV
# authoring endpoint (later phase) and the client registry can write there.
RUN mkdir -p /data/kits && chown -R appuser:appuser /data
ENV QM_KITS_ROOT=/data/kits
ENV QM_CLIENT_REGISTRY_PATH=/data/client_registry.json
ENV QM_APP_TOKENS_PATH=/data/app_tokens.json
ENV QM_WEBUI_DIST=/app/server/webui_dist

WORKDIR /app/server

USER appuser

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

VOLUME ["/data/kits"]

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips=*"]
