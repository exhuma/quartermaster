# Changelog

All notable changes to the Quartermaster server are documented here. The
format is based on [Keep a Changelog](https://keepachangelog.com/), and the
project aims to follow semantic versioning.

## v0.1.0 — Initial public release

First public release of **Quartermaster**, a self-hosted MCP server that
serves versioned AI instruction kits to coding agents.

- FastAPI + FastMCP backend exposing the kit MCP tools (`list_kits`,
  `get_kit_outline`, `get_kit`, `list_kit_versions`, `compare_kit_versions`)
  and the V2 trait-based selector (`list_available_traits`, `select_kits`,
  `explain_kit_candidate`).
- Keycloak-gated auth (`JWTAuthMiddleware`) terminating inside the
  application, with RFC 9728 / RFC 8414 OAuth discovery for OAuth-aware
  clients, and an optional fixed-header mode.
- REST admin API (`/api`) for kit CRUD, client registration, integration
  discovery, and app-token management; embedded WebDAV authoring at `/dav`.
- Vue 3 + Vuetify single-page web UI for kit management and MCP integration
  setup.
- The kit catalog is decoupled from the server: supplied at runtime via
  `KITS_ROOT` and never bundled into the image.
- Container image published to GitHub Container Registry.
