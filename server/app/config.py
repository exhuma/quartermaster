"""
Application settings loaded from environment variables via pydantic-settings.
"""

from __future__ import annotations

import json
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlparse

from pydantic import (
    BaseModel,
    PrivateAttr,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class KitLayerConfig(BaseModel):
    """
    Configuration for a single named kit layer.

    Layers are ordered base → overlay (first entry = lowest priority).
    A kit name present in multiple layers is owned entirely by the
    highest-priority layer that contains it (kit-level shadowing), except
    for sections the base layer marks ``binding = true`` — those always
    appear in the merged kit even when shadowed.

    :param name: URL-safe identifier, e.g. ``"company"`` or ``"team-local"``.
        Used as the layer path segment in ``/api/kits/layers/{name}`` and
        ``/dav/{name}/``.
    :param path: Local filesystem path to the kit catalog root for this layer.
    :param readonly: When true, REST and WebDAV writes to this layer are
        rejected with HTTP 403.
    """

    name: str
    path: Path
    readonly: bool = False


def load_layers_from_toml(file_path: Path) -> list[KitLayerConfig]:
    """
    Parse an ordered list of kit layers from a TOML config file.

    The file lists layers base → overlay as an array of tables::

        # /data/layers.toml
        [[layer]]
        name = "company"
        path = "company-kits"   # relative → resolved against this file's dir
        readonly = true

        [[layer]]
        name = "team"
        path = "/data/team-kits"

    Relative ``path`` values are resolved against the **directory of the
    TOML file** (not the process CWD), so a self-contained
    ``layers.toml`` plus sibling catalog directories is portable. Absolute
    paths are used as-is.

    This is the single shared parser used by both :class:`Settings` and the
    WebDAV mount, so the file schema lives in exactly one place.

    :param file_path: Path to the layers TOML file.
    :returns: Ordered, non-empty list of :class:`KitLayerConfig`.
    :raises FileNotFoundError: If *file_path* does not exist.
    :raises ValueError: If the document is malformed or defines no layers.
    """
    if not file_path.exists():
        raise FileNotFoundError(
            f"QM_KIT_LAYERS_FILE points at a missing file: {file_path}"
        )
    try:
        raw = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Kit layers file {file_path} is not valid TOML: {exc}"
        ) from exc

    entries = raw.get("layer")
    if not isinstance(entries, list) or not entries:
        raise ValueError(
            f"Kit layers file {file_path} must define at least one "
            f"[[layer]] entry"
        )

    base_dir = file_path.resolve().parent
    layers: list[KitLayerConfig] = []
    seen_names: set[str] = set()
    for pos, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(
                f"Kit layers file {file_path}: [[layer]] #{pos} must be "
                f"a table"
            )
        name = str(entry.get("name", "")).strip()
        path_str = str(entry.get("path", "")).strip()
        readonly = bool(entry.get("readonly", False))
        if not name or not path_str:
            raise ValueError(
                f"Kit layers file {file_path}: [[layer]] #{pos} must set "
                f"both 'name' and 'path'"
            )
        if name in seen_names:
            raise ValueError(
                f"Kit layers file {file_path}: duplicate layer name "
                f"{name!r}"
            )
        seen_names.add(name)
        layer_path = Path(path_str)
        if not layer_path.is_absolute():
            layer_path = (base_dir / layer_path).resolve()
        layers.append(
            KitLayerConfig(name=name, path=layer_path, readonly=readonly)
        )
    return layers


def load_version_policy_from_toml(
    file_path: Path,
) -> dict[str, dict[str, Any]]:
    """
    Parse an optional per-kit version-policy TOML file.

    The operator declares, per kit, a minimum acceptable major and/or a
    list of deprecated majors. Quartermaster only *surfaces* this in the
    ``version_advisory``; the calling agent enforces it (prompt/refuse)::

        [kits.module-auth-oidc]
        min_version = "v2"
        deprecated = ["v1"]

    :param file_path: Path to the policy TOML file.
    :returns: ``{kit_name: {"min_version": str | None,
        "deprecated": list[str]}}`` (empty when the file is absent).
    :raises ValueError: If the document is not valid TOML.
    """
    if not file_path.exists():
        return {}
    try:
        raw = tomllib.loads(file_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Version policy file {file_path} is not valid TOML: {exc}"
        ) from exc
    kits = raw.get("kits", {})
    policy: dict[str, dict[str, Any]] = {}
    if isinstance(kits, dict):
        for name, entry in kits.items():
            if not isinstance(entry, dict):
                continue
            min_version = entry.get("min_version")
            deprecated = entry.get("deprecated", [])
            policy[str(name)] = {
                "min_version": (
                    str(min_version) if min_version else None
                ),
                "deprecated": [
                    str(v) for v in deprecated
                    if isinstance(deprecated, list)
                ],
            }
    return policy


# Server package root (server/), used for dev-only default data paths.
_SERVER_ROOT = Path(__file__).resolve().parents[1]
_CLIENT_REGISTRY_DEFAULT = _SERVER_ROOT / "var" / "client_registry.json"
_APP_TOKENS_DEFAULT = _SERVER_ROOT / "var" / "app_tokens.json"
# Built web-UI assets. Empty/missing → the SPA is simply not served (the
# API and MCP still work); the Docker image points this at the built dist.
_WEBUI_DIST_DEFAULT = _SERVER_ROOT / "webui_dist"
# Rendered Sphinx documentation. Empty/missing → the /docs site is simply not
# served (the API and MCP still work); the Docker image points this at the
# built HTML produced by the docs stage.
_DOCS_DIST_DEFAULT = _SERVER_ROOT / "docs_dist"
_EMBEDDINGS_CACHE_DEFAULT = _SERVER_ROOT / "var" / "embeddings"
_METRICS_LOCAL_DB_DEFAULT = _SERVER_ROOT / "var" / "metrics.db"
_ROLE_STORE_DEFAULT = _SERVER_ROOT / "var" / "roles.toml"
_PRIVATE_KITS_DEFAULT = _SERVER_ROOT / "var" / "private-kits"
_USER_MEMORY_DEFAULT = _SERVER_ROOT / "var" / "user-memory.toml"


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
    :param kits_root: Path to a single-root kit catalog directory.
        Single-root option; set ``QM_KITS_ROOT`` when you have one catalog.
        Superseded by ``kit_layers_file`` / ``QM_KIT_LAYERS_FILE`` for
        multi-root layered setups — if both are set, ``kit_layers_file`` wins.
        At least one of ``kits_root`` or ``kit_layers_file`` is required.
    :param kit_layers_file: Path to a TOML file listing named kit layers
        (``QM_KIT_LAYERS_FILE``), ordered base → overlay::

            [[layer]]
            name = "company"
            path = "company-kits"   # relative → resolved against this file
            readonly = true

            [[layer]]
            name = "team"
            path = "team-kits"

        Relative layer ``path`` values are resolved against the file's own
        directory.  If set, ``kits_root`` is ignored.  At least one layer
        must be writable (``readonly`` omitted or ``false``).
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
    :param docs_dist: Directory of rendered Sphinx documentation to serve at
        ``/docs``. When it does not exist the docs site is simply not mounted
        (the API and MCP are unaffected). The Docker image points this at the
        HTML produced by the docs build stage.
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
    :param issue_backend: Which maintainer-notification backend
        materializes kit-extension/gap requests: ``"github"``, ``"gitlab"``,
        or ``"none"`` (disable). Unset defaults to ``"github"`` for
        back-compat with deployments that only set ``GITHUB_*`` settings.
    :param gitlab_base_url: Base URL of the GitLab instance (default
        ``https://gitlab.com``; override for self-hosted GitLab).
    :param gitlab_project_id: GitLab project id or URL-encoded path used
        when materializing kit extension requests as project issues.
    :param gitlab_token: GitLab personal/project access token with
        permission to create issues in ``gitlab_project_id``.
    :param gitlab_default_assignee_id: Optional default assignee user id
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
    :param sampling_enabled: When true (default), ``resolve_kits`` prefers MCP
        sampling (the connecting client's own LLM) for trait inference when the
        client supports it, ahead of the configured HTTP LLM / embeddings /
        lexical chain. Set false to never sample.
    :param elicitation_enabled: When true (default), ``resolve_kits`` asks the
        user (via MCP elicitation) to disambiguate an empty or low-confidence
        task when the client supports it, instead of silently degrading. Set
        false to preserve the legacy empty-task ``ValueError`` / best-effort
        behaviour.
    :param resolve_elicit_min_confidence: Selection-confidence threshold below
        which ``resolve_kits`` will elicit clarification (when elicitation is
        supported and enabled). Higher values elicit more eagerly.
    :param gap_detection_enabled: When true (default), ``resolve_kits`` runs a
        catalog-recall check (see ``app/gap.py``) whenever trait inference
        finds nothing for a task, to confirm the catalog genuinely has no
        related content before surfacing a ``gap`` in the response.
    :param gap_recall_min_score: Minimum cosine similarity (embedding recall
        path) for a trait pseudo-document to count as a real catalog match;
        below this, the task is treated as a genuine gap.
    :param gap_lexical_min_overlap: Minimum word-overlap count (lexical
        recall path, used when no embedder is available) for a trait
        pseudo-document to count as a real catalog match.
    :param user_memory_enabled: When true (default), ``resolve_kits`` derives
        a small per-caller profile from that caller's own resolve history and
        uses it as a bounded ranking nudge (never a filter). Set false to
        disable memory derivation and personalization entirely.
    :param user_memory_store_path: Path to the per-subject memory TOML file.
        A rebuildable derived cache, not a source of truth — safe to delete.
    :param user_memory_ttl_seconds: How long a cached profile is reused
        before ``resolve_kits`` lazily rebuilds it from metrics history.
    :param user_memory_half_life_days: Exponential-decay half-life for
        weighting a caller's resolve history when deriving their profile.
    :param user_memory_top_domains: Max domains kept in a derived profile.
    :param user_memory_top_kits: Max kit names kept in a derived profile.
    :param user_memory_top_languages: Max languages kept in a derived profile.
    :param user_memory_top_frameworks: Max frameworks kept in a derived
        profile.
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
    :param metrics_local_enabled: When true (default), record usage events into
        a local SQLite store that feeds the in-app Metrics dashboard. This is
        independent of OpenTelemetry, so the dashboard works even when OTLP is
        broken or unconfigured. Set false to disable local recording entirely.
    :param metrics_local_db_path: Path to the local metrics SQLite database.
        Defaults to a dev-only path under ``server/var/``; set to a writable
        data-volume path in production (e.g. ``/data/metrics.db``) so the
        rolling window survives container restarts.
    :param metrics_local_retention_days: How many days of usage events the local
        store keeps before pruning (default 7). Long-term history is delegated
        to OpenTelemetry; this store is a short, capped complement.
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
    kits_root: Path | None = None
    kit_layers_file: Path | None = None
    resource_base_url: str
    webui_keycloak_client_id: str = "quartermaster-webui"
    client_registry_path: Path = _CLIENT_REGISTRY_DEFAULT
    app_tokens_path: Path = _APP_TOKENS_DEFAULT
    # Authorization (module-authz). Roles map an IdP subject (Keycloak ``sub``)
    # to ``editor``/``consumer``; the store defaults to consumer for unknown
    # users. ``initial_editors`` seeds bootstrap editors that can never be
    # locked out (they always resolve to editor and cannot be revoked via the
    # store). Accepts a JSON array or a comma-separated list of subjects.
    role_store_path: Path = _ROLE_STORE_DEFAULT
    initial_editors: Annotated[list[str], NoDecode] = []
    # Owner-only private kits live under a per-owner subtree of this root
    # (never the public catalog), so a missed enumeration path cannot leak
    # them. In production, point this at a writable data volume.
    private_kits_root: Path = _PRIVATE_KITS_DEFAULT
    dav_require_tls: bool = True
    webui_dist: Path = _WEBUI_DIST_DEFAULT
    docs_dist: Path = _DOCS_DIST_DEFAULT
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
    issue_backend: str | None = None
    gitlab_base_url: str = "https://gitlab.com"
    gitlab_project_id: str | None = None
    gitlab_token: str | None = None
    gitlab_default_assignee_id: int | None = None
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
    # MCP sampling + elicitation for the one-shot ``resolve_kits`` tool. When
    # the connecting client supports them, sampling is the preferred trait
    # engine (borrows the client's own LLM, no QM_LLM_PROVIDER needed) and
    # elicitation disambiguates empty/low-confidence tasks. Both degrade
    # gracefully to the deterministic chain when the client cannot service
    # them, and either can be disabled here.
    sampling_enabled: bool = True
    elicitation_enabled: bool = True
    resolve_elicit_min_confidence: float = 0.25
    # Catalog-recall gap detection: when trait inference finds nothing for a
    # task, confirm it against the whole catalog (not just the inferred
    # vocabulary) before treating it as a gap worth reporting. See app/gap.py.
    gap_detection_enabled: bool = True
    gap_recall_min_score: float = 0.30
    gap_lexical_min_overlap: int = 1
    # Agent-in-the-loop clarification: when trait inference is partial but a
    # pivotal required trait dimension is missing (e.g. "add a database" with no
    # language), ``resolve_kits`` returns a structured ``clarification`` block
    # for the calling agent to answer from repo inspection, then re-resolve —
    # non-blocking, distinct from the human ``ctx.elicit`` path. See
    # app/clarify.py.
    clarification_enabled: bool = True
    clarification_max_questions: int = 2
    clarification_min_blocking_kits: int = 1
    # Always-apply policy kits: a kit manifest may set ``always_apply: true`` so
    # its ``always_load`` content is injected on every resolve whose gates it
    # satisfies, bypassing the score threshold (see app/kits.select_kits_v2).
    # This kill-switch disables that injection catalog-wide.
    policy_enabled: bool = True
    # Per-user memory: a small, capped profile derived from each caller's own
    # resolve_kits history (see app/storage/user_memory.py), used only as a
    # bounded ranking nudge (app/personalization.py) — never a filter.
    user_memory_enabled: bool = True
    user_memory_store_path: Path = _USER_MEMORY_DEFAULT
    user_memory_ttl_seconds: int = 3600
    user_memory_half_life_days: float = 30.0
    user_memory_top_domains: int = 5
    user_memory_top_kits: int = 5
    user_memory_top_languages: int = 3
    user_memory_top_frameworks: int = 3
    # Observability (OpenTelemetry metrics + traces). OTLP push is driven by
    # the standard OTEL_* env vars read by the SDK directly; only the
    # Prometheus pull endpoint and its auth posture are Quartermaster toggles.
    metrics_prometheus_enabled: bool = False
    metrics_allow_anonymous: bool = False
    metrics_section_level: bool = False
    # Always-on local metrics store (independent of OTEL) feeding the in-app
    # Metrics dashboard. Short rolling window; long-term history is OTEL's job.
    metrics_local_enabled: bool = True
    metrics_local_db_path: Path = _METRICS_LOCAL_DB_DEFAULT
    metrics_local_retention_days: int = 7
    # Kit version pinning (see app/kits.py resolve_effective_version). Repos
    # record their per-kit major in a repo-side .quartermaster.toml; the server
    # is stateless about pins. These toggles cover the two things the server
    # *can* own: adoption telemetry and an optional operator version policy.
    version_telemetry_enabled: bool = True
    # When true (default), an unpinned kit that has shipped a breaking change is
    # served at its earliest major with an upgrade advisory. Set false to revert
    # to latest-wins for unpinned multi-version kits.
    conservative_default_enabled: bool = True
    # Optional per-kit min_version/deprecated policy, surfaced in the advisory.
    version_policy_file: Path | None = None
    _version_policy: dict[str, dict[str, Any]] | None = PrivateAttr(
        default=None
    )

    # Layers parsed from ``kit_layers_file`` once, at validation time, so the
    # file is read a single time and ``effective_layers`` stays cheap.
    _file_layers: list[KitLayerConfig] | None = PrivateAttr(default=None)

    @field_validator("initial_editors", mode="before")
    @classmethod
    def _split_initial_editors(cls, value: object) -> object:
        """Accept a comma-separated ``QM_INITIAL_EDITORS`` in addition to JSON.

        Keycloak subjects are comma-free, so a plain ``sub-a,sub-b`` string is
        the friendliest ops input; a JSON array still works too.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                # JSON array. NoDecode skips pydantic's own JSON pass, so parse
                # it here; fall back to comma-splitting on malformed JSON.
                try:
                    return json.loads(stripped)
                except json.JSONDecodeError:
                    pass
            return [s.strip() for s in stripped.split(",") if s.strip()]
        return value

    @model_validator(mode="after")
    def _validate_kit_config(self) -> Settings:
        """Ensure a kit root is configured with a writable layer."""
        if self.kit_layers_file is not None:
            self._file_layers = load_layers_from_toml(self.kit_layers_file)

        if self.kits_root is None and self._file_layers is None:
            raise ValueError(
                "No kit catalog configured. Set either QM_KIT_LAYERS_FILE "
                "(a TOML layers file) or QM_KITS_ROOT (a single catalog "
                "directory — a local checkout in dev, /data/kits in "
                "production)."
            )

        # kits_root maps to one always-writable default layer, so the writable
        # check only applies to a configured layers file.
        if self._file_layers is not None and all(
            layer.readonly for layer in self._file_layers
        ):
            raise ValueError(
                "At least one kit layer must be writable "
                "(not all layers can have readonly=true)."
            )
        return self

    @property
    def effective_layers(self) -> list[KitLayerConfig]:
        """
        Return the ordered list of kit layers (base → overlay, last =
        highest priority).

        Precedence: layers from ``kit_layers_file`` (TOML) win; failing that,
        ``kits_root`` is wrapped in a single ``"default"`` layer for
        single-root deployments.

        :returns: Non-empty list of :class:`KitLayerConfig`, lowest
            priority first.
        """
        if self._file_layers is not None:
            return self._file_layers
        # kits_root is guaranteed non-None here by the model validator
        return [KitLayerConfig(name="default", path=self.kits_root)]  # type: ignore[arg-type]

    def version_policy(self) -> dict[str, dict[str, Any]]:
        """
        Return the parsed per-kit version policy (cached), or ``{}``.

        Read once from ``version_policy_file`` on first access; a missing
        file yields an empty policy (no constraints).
        """
        if self._version_policy is None:
            if self.version_policy_file is not None:
                self._version_policy = load_version_policy_from_toml(
                    Path(self.version_policy_file)
                )
            else:
                self._version_policy = {}
        return self._version_policy

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
