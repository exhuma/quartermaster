"""
Application settings loaded from environment variables via pydantic-settings.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Server package root (server/), used for dev-only default data paths.
_SERVER_ROOT = Path(__file__).resolve().parents[1]
_CLIENT_REGISTRY_DEFAULT = _SERVER_ROOT / "var" / "client_registry.json"
_APP_TOKENS_DEFAULT = _SERVER_ROOT / "var" / "app_tokens.json"
# Built web-UI assets. Empty/missing → the SPA is simply not served (the
# API and MCP still work); the Docker image points this at the built dist.
_WEBUI_DIST_DEFAULT = _SERVER_ROOT / "webui_dist"
_EMBEDDINGS_CACHE_DEFAULT = _SERVER_ROOT / "var" / "embeddings"


class Settings(BaseSettings):
    """
    Runtime configuration for the Quartermaster MCP server.

    All values are read from environment variables (case-insensitive).
    Required variables must be present; optional variables fall back to
    the declared default.

    :param keycloak_url: Base URL of the Keycloak server,
        e.g. ``https://auth.example.com``.  Trailing slash is stripped
        automatically.
    :param keycloak_realm: Name of the Keycloak realm that issues tokens.
    :param keycloak_audience: If set, the ``aud`` claim in incoming JWTs
        must contain this value.  Leave unset to skip audience validation
        (useful when service-account tokens do not carry an explicit
        audience).
    :param tls_ca_bundle: Optional path to a PEM CA bundle used to verify
        Keycloak's TLS certificate on outbound calls (JWKS fetch and the
        optional Copilot token-endpoint check).  Set this when Keycloak is
        served by a private/internal CA that is not in the system trust
        store.  Ignored when ``tls_insecure_skip_verify`` is true.
    :param tls_insecure_skip_verify: When true, disables TLS certificate
        and hostname verification for outbound Keycloak calls.  **For quick
        POC/testing only — never use in production.**  Takes precedence over
        ``tls_ca_bundle``.
    :param kits_root: Path to the ``kits/`` directory where kit
        subdirectories live.  Required — the catalog is decoupled from
        this server and is never bundled with it. Point ``KITS_ROOT`` at
        your kit catalog: a local checkout in dev, or the mounted volume
        in production (e.g. ``/data/kits``).
    :param webui_keycloak_client_id: Keycloak public client id used by
        the browser web UI for the OIDC authorization-code + PKCE flow.
        Advertised to the SPA via runtime config.
    :param client_registry_path: Path to the JSON file recording
        registered client User-Agents. Non-browser clients must register
        their User-Agent before calling the API or MCP endpoint. Defaults
        to a dev-only path under ``server/var/``; set this to a writable
        location on the data volume in production (e.g.
        ``/data/client_registry.json``).
    :param webui_dist: Directory of built web-UI assets to serve. When it
        does not exist the SPA is simply not mounted (the API and MCP are
        unaffected). The Docker image points this at the built ``dist``.
    :param app_tokens_path: Path to the JSON file storing hashed per-user
        WebDAV app tokens. Defaults to a dev-only path under ``server/var/``;
        set to a writable data-volume path in production.
    :param dav_require_tls: When true (default), the ``/dav`` WebDAV
        endpoint refuses HTTP Basic over plain HTTP — credentials must
        travel over TLS. Set false only for local non-TLS testing.
    :param resource_base_url: Public origin (scheme + host, no path) of
        this server, e.g. ``https://instructions.example.com``.  Used
        to construct the OAuth metadata URLs and ``WWW-Authenticate``
        headers that enable OAuth-aware clients to discover Keycloak
        automatically.  Must not include a trailing slash or path.
    :param oauth_scopes: Whitespace-separated list of OAuth scopes that
        this Keycloak client accepts.  Advertised in the
        ``/.well-known/oauth-authorization-server`` metadata so that
        OAuth clients (e.g. VS Code) request only these scopes and
        Keycloak does not reject the authorization request.  Defaults
        to ``openid profile email``.
    :param dev_auth_enabled: Dev-only gate. When true, the ``/auth/dev/*``
        token-minting router is mounted so the app can run locally without
        an IdP. **Must be unset/false in production** (deploy invariant);
        when false the dev routes are a plain 404, not merely rejected.
    :param dev_shared_secret: Dev-only HS256 signing secret. When set, the
        middleware accepts self-minted HS256 dev tokens (still enforcing the
        same ``iss``/``aud`` as real tokens); when unset, HS256 tokens are
        rejected outright — which is the safe default. **Never commit a
        value and never set it in production.**
    :param copilot_auth_enabled: When true, allow fixed-header
        authentication for clients that cannot present a bearer token.
        Header credentials are validated against the IDP token
        endpoint. This supplements (but does not replace) JWT bearer
        validation.
    :param copilot_auth_timeout_seconds: Timeout for token-endpoint
        requests used for fixed-header validation.
    :param github_owner: Optional GitHub repository owner used when
        materializing kit extension requests as repository issues.
    :param github_repo: Optional GitHub repository name used when
        materializing kit extension requests as repository issues.
    :param github_token: Optional GitHub personal access token with
        permission to create issues in ``github_owner/github_repo``.
    :param github_default_assignee: Optional default assignee username
        to attach to created issues.
    :param embeddings_enabled: When true (default), the ``resolve_kits``
        tool uses local embeddings to infer traits and rank sections.
        Degrades to a lexical floor if the embedding dependency or model
        is unavailable; set false for a slim, lexical-only deployment.
    :param embeddings_model: Embedding model id loaded by the embedding
        backend (default ``BAAI/bge-small-en-v1.5``).
    :param embeddings_cache_dir: Directory for cached trait/section
        embeddings, keyed by model id and catalog fingerprint.
    :param embeddings_min_score: Minimum cosine similarity for a trait to
        be inferred by the embedding engine.
    :param embeddings_top_k_per_category: Maximum traits the embedding
        engine emits per category.
    :param llm_provider: Optional LLM backend selector for ``resolve_kits``
        trait inference: ``"openai"`` (OpenAI-compatible endpoint) or
        ``"anthropic"``. Unset disables the LLM layer entirely.
    :param llm_base_url: Base URL for the OpenAI-compatible endpoint
        (covers Ollama/vLLM/llama.cpp and cloud providers).
    :param llm_model: Model id passed to the configured LLM backend.
    :param llm_api_key: API key/token for the configured LLM backend.
    :param llm_timeout_seconds: Per-request timeout for LLM calls; on
        timeout the resolver falls back to embeddings, then lexical.
    :param metrics_prometheus_enabled: When true, mount a ``GET /metrics``
        Prometheus pull endpoint (requires the ``telemetry`` extra). OTLP
        push is configured separately via the standard ``OTEL_*`` env vars
        and needs no Quartermaster toggle. Default false.
    :param metrics_allow_anonymous: When false (default), the ``/metrics``
        endpoint requires app-token HTTP Basic auth (the same token used for
        ``/dav``; Prometheus supports this via ``basic_auth``). Set true only
        when ``/metrics`` is isolated at the network layer (internal
        interface, firewall, or reverse-proxy auth).
    :param metrics_section_level: When true, emit per-section delivery metrics
        (``qm.section.deliveries``). Off by default to bound metric
        cardinality on large catalogs.
    """

    # All environment variables are prefixed with the application name
    # (``QM_``) per the module-fastapi kit, e.g. ``QM_KEYCLOAK_URL``. The few
    # values read at import/bootstrap time outside this class (LOG_CONFIG,
    # KITS_ROOT for the /dav mount, etc.) use the same ``QM_`` prefix
    # explicitly.
    model_config = SettingsConfigDict(
        env_prefix="QM_",
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
    )

    keycloak_url: str
    keycloak_realm: str
    keycloak_audience: str | None = None
    tls_ca_bundle: Path | None = None
    tls_insecure_skip_verify: bool = False
    kits_root: Path
    resource_base_url: str
    webui_keycloak_client_id: str = "quartermaster-webui"
    client_registry_path: Path = _CLIENT_REGISTRY_DEFAULT
    app_tokens_path: Path = _APP_TOKENS_DEFAULT
    dav_require_tls: bool = True
    webui_dist: Path = _WEBUI_DIST_DEFAULT
    # Dev-only auth bypass (module-dev-auth-bypass). Both default off; never
    # set in production. dev_shared_secret has NO default — an unset secret
    # is what makes HS256 rejection the safe default.
    dev_auth_enabled: bool = False
    dev_shared_secret: str | None = None
    oauth_scopes: list[str] = ["openid", "profile", "email"]
    copilot_auth_enabled: bool = False
    copilot_auth_timeout_seconds: float = 3.0
    github_owner: str | None = None
    github_repo: str | None = None
    github_token: str | None = None
    github_default_assignee: str | None = None
    # Server-side inference for the one-shot ``resolve_kits`` tool. The
    # embedding baseline is on by default but degrades to a lexical floor when
    # the dependency/model is unavailable (so a slim deployment can set
    # ``QM_EMBEDDINGS_ENABLED=false``). The pluggable LLM is off unless
    # ``llm_provider`` and its required fields are set.
    embeddings_enabled: bool = True
    embeddings_model: str = "BAAI/bge-small-en-v1.5"
    embeddings_cache_dir: Path = _EMBEDDINGS_CACHE_DEFAULT
    embeddings_min_score: float = 0.30
    embeddings_top_k_per_category: int = 4
    llm_provider: str | None = None  # "openai" | "anthropic"
    llm_base_url: str | None = None  # OpenAI-compatible base URL
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_timeout_seconds: float = 8.0
    # Observability (OpenTelemetry metrics + traces). OTLP push is driven by
    # the standard OTEL_* env vars read by the SDK directly; only the
    # Prometheus pull endpoint and its auth posture are Quartermaster toggles.
    metrics_prometheus_enabled: bool = False
    metrics_allow_anonymous: bool = False
    metrics_section_level: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def jwks_url(self) -> str:
        """
        JWKS endpoint for the configured Keycloak realm.

        :returns: Full JWKS URL string.
        """
        base = self.keycloak_url.rstrip("/")
        return (
            f"{base}/realms/{self.keycloak_realm}"
            "/protocol/openid-connect/certs"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def keycloak_issuer(self) -> str:
        """
        Expected ``iss`` claim value for tokens issued by this realm.

        Used only for JWT validation; never advertised to OAuth clients.

        :returns: Issuer URL string.
        """
        base = self.keycloak_url.rstrip("/")
        return f"{base}/realms/{self.keycloak_realm}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def server_origin(self) -> str:
        """
        Scheme + host extracted from ``resource_base_url``.

        Well-known endpoints are always served at the server root,
        regardless of any path prefix in ``resource_base_url``.

        :returns: Origin URL string, e.g. ``https://example.com``.
        """
        parsed = urlparse(self.resource_base_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def oauth_metadata_url(self) -> str:
        """
        URL of the OAuth Protected Resource Metadata document (RFC 9728).

        Advertised in ``WWW-Authenticate`` response headers so that
        OAuth-aware clients can discover the authorization server
        automatically.  Always served at the server root regardless of
        any path in ``resource_base_url``.

        :returns: Full URL to ``/.well-known/oauth-protected-resource``.
        """
        return f"{self.server_origin}/.well-known/oauth-protected-resource"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def authorization_endpoint(self) -> str:
        """
        Keycloak authorization endpoint for the configured realm.

        :returns: Full authorization endpoint URL.
        """
        return f"{self.keycloak_issuer}/protocol/openid-connect/auth"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def token_endpoint(self) -> str:
        """
        Keycloak token endpoint for the configured realm.

        :returns: Full token endpoint URL.
        """
        return f"{self.keycloak_issuer}/protocol/openid-connect/token"

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return the cached application Settings singleton.

    :returns: Fully validated Settings instance.
    """
    return Settings()  # type: ignore  # fields loaded from env vars at runtime
