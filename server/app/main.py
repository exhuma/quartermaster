"""FastAPI + FastMCP application entry point.

Outer FastAPI application that:

- Exposes a public ``GET /health`` liveness probe.
- Exposes a public ``GET /.well-known/oauth-protected-resource``
  metadata document (RFC 9728) so that OAuth-aware clients such as
  VS Code can discover the Keycloak authorization server automatically.
- Mounts a FastMCP streamable-HTTP endpoint at ``/kits/mcp`` with V2
    discovery + content tools: ``list_kits``, ``list_available_traits``,
    ``list_prompts``, ``get_prompt``, ``select_kits``, ``resolve_kits``,
    ``explain_kit_candidate``, ``get_kit``, ``list_kit_versions``,
    and ``compare_kit_versions``.  The gap tools
    ``check_existing_gap_issue`` / ``request_clarification_or_addition``
    are registered only when a maintainer-notification backend (GitHub or
    GitLab) is configured.  The mount also ships
    server-level
    ``instructions`` (see :data:`MCP_INSTRUCTIONS`) describing the
    intended per-task trait-reflection workflow; clients receive it in
    the MCP ``initialize`` response.
- Applies :class:`~app.auth.JWTAuthMiddleware` to every request,
  protecting the ``/kits/mcp`` mount while leaving the public endpoints
  open.

Start the server from the ``server/`` directory:

.. code-block:: console

    uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from app.logging_config import configure_logging

# Configure logging before importing modules that grab loggers, so import-time
# records are formatted. Operators control this via QM_LOG_CONFIG / QM_LOG_LEVEL
# (see app/logging_config.py) without rebuilding the image.
configure_logging()

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastmcp import Context, FastMCP
from pydantic import ValidationError

logger = logging.getLogger(__name__)

from app import health as health_probes
from app import telemetry
from app.auth import JWTAuthMiddleware
from app.authz import EditorRequiredError, PrivateKitAccessError
from app.config import get_settings
from app.dav.webdav_app import mount_dav
from app.identity import current_sub
from app.kits import (
    KitConflictError,
    KitLayerNotFoundError,
    KitLayerReadonlyError,
    KitNotFoundError,
    KitSectionNotFoundError,
    KitValidationError,
    KitVersionNotFoundError,
    explain_kit_v2,
    list_all_kits,
    list_available_traits_v2,
    list_catalog_v2,
    read_kit,
    read_kit_outline,
    select_kits_v2,
)
from app.kits import (
    compare_kit_versions as _compare_kit_versions,
)
from app.mcp_identity import MCPIdentityASGI
from app.mcp_logging import ToolCallAuditMiddleware
from app.middleware import (
    RequestLoggingMiddleware,
    SecurityHeadersMiddleware,
    VersionHeaderMiddleware,
)
from app.notifications import (
    check_existing_kit_extension_issue as _check_existing_kit_extension_issue,
)
from app.notifications import gap_tools_enabled
from app.notifications import request_kit_extension as _request_kit_extension
from app.observability import local_store
from app.personalization import profile_hint
from app.prompts import get_canned_prompt as _get_canned_prompt
from app.prompts import list_canned_prompts as _list_canned_prompts
from app.resolver import build_ranker
from app.resolver import resolve_kits as _resolve_kits
from app.routers import (
    app_tokens,
    clients,
    integration,
    kits_admin,
    kits_layers,
)
from app.routers import (
    me as me_router,
)
from app.routers import (
    metrics as metrics_router,
)
from app.routers import (
    private_kits as private_kits_router,
)
from app.routers import (
    roles as roles_router,
)
from app.sampling import (
    SamplingTraitEngine,
    client_supports_elicitation,
    client_supports_sampling,
)
from app.storage import user_memory
from app.storage.kit_writes import KitPathError
from app.tokens import count_tokens
from app.traits import load_vocabulary
from app.user_agent import UserAgentMiddleware
from app.version import app_version
from app.webui import mount_webui

# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

_INSTRUCTIONS_BODY = """\
This MCP serves versioned AI *instruction kits* — agent-facing guidance for
specific architecture, tooling, and capability choices (for example: local
auth, OIDC, a FastAPI + Vuetify stack). Kits are loaded on demand as extra
context; their files are never copied into the target project.

**Use kits per task, not once per project.** Avoid hard-coding a fixed kit
list in CLAUDE.md / AGENTS.md — a fixed list loads too much or too little. The
traits a task touches often only emerge during the conversation: a request to
"add authentication" may resolve to OIDC after some discussion, bringing OIDC
kits into scope that were irrelevant before. A static list cannot react to
that.

**Default path — start every task by calling `resolve_kits`.** Pass a
plain-language description of the work (`resolve_kits(task="…")`). The server
maps the task onto its trait vocabulary, ranks the matching kits, and returns
the recommendation with each kit's `always_load` sections already inlined —
collapsing the whole discovery sequence into one call and keeping it out of
your context. Re-run it whenever the task's direction shifts and new traits
come into scope. Pull any extra sections it lists under `fetch_on_demand` with
`get_kit(name, sections=[…])` when you reach that aspect.

Use the manual loop below only when you need finer control: you have already
mapped the task to explicit traits, you want to inspect ranking diagnostics,
or you are loading several kits incrementally.

1. **Discover coverage** — call `list_available_traits` for the trait
   vocabulary (languages, frameworks, capabilities, contexts) and `list_kits`
   for the available kits.
2. **Map the task to traits** — this server's advertised vocabulary is
   authoritative, so normalize the developer's wording onto supported
   `languages`/`frameworks`/`capabilities`/`contexts` instead of inventing
   trait names; infer which traits the task touches from the repository and
   intent, and revisit as the direction firms up. (`resolve_kits` does this
   step for you.)
3. **Load matching guidance** — call `select_kits` with the task's traits (use
   `broaden=True` if `broadening_recommended` is set, and retry with adjacent
   supported traits when coverage stays low — before concluding no kit
   applies), narrow with `explain_kit_candidate`, then load each chosen kit.
   Re-run this when new traits come into scope mid-task.
4. **Load lean** — call `get_kit_outline` to see a kit's sections, then
   `get_kit` with `sections=[…]` to pull only the sections the current step
   needs (start with the ones flagged `always_load`). Read a kit's full text
   (omit `sections`) only when you're implementing all of it. For tasks that
   touch several kits, load each kit's content when you reach that aspect, not
   all up front.

For a compact, operational version of this trait-selection routine, fetch the
bootstrap prompt from the prompt registry (`list_prompts` → `get_prompt`).
"""

# Appended only when the gap-request tools are registered (i.e. a maintainer
# notification backend is configured). When they are not, the agent must not
# be told to call tools that do not exist.
_INSTRUCTIONS_GAP_SENTENCE = (
    "If the task needs a capability no kit covers, call "
    "`check_existing_gap_issue` and then `request_clarification_or_addition` "
    "to file a gap. "
)
_INSTRUCTIONS_HARDCODE_SENTENCE = (
    "Hard-coding kits is acceptable only when a project's relevant kits are "
    "genuinely stable; otherwise prefer per-task reflection."
)


def _build_mcp_instructions(*, gap_enabled: bool) -> str:
    """Assemble the server-level MCP instructions.

    The gap-filing sentence is included only when *gap_enabled* is true, so
    the instructions never reference tools that are not registered.
    """
    closing = _INSTRUCTIONS_HARDCODE_SENTENCE
    if gap_enabled:
        closing = _INSTRUCTIONS_GAP_SENTENCE + closing
    return f"{_INSTRUCTIONS_BODY}\n{closing}\n"


def _gap_tools_enabled() -> bool:
    """Return whether a maintainer-notification backend is configured.

    Reads the same source as :func:`app.notifications.get_issue_backend`
    (settings, which also honor ``.env``), but tolerates an incompletely
    configured environment so it is safe to call at import time: when required
    Keycloak settings are absent (e.g. during test collection) the gap tools
    are simply treated as disabled.
    """
    try:
        settings = get_settings()
    except ValidationError:
        return False
    return gap_tools_enabled(settings)


def _warm_embeddings() -> None:
    """Eagerly warm the embedding model at startup (best-effort).

    Moves the fastembed model load + trait-vocabulary embedding off the first
    ``resolve_kits`` request (the cold start that otherwise times out in a
    fresh pod) and onto startup. Any failure is swallowed: the resolver still
    degrades to lexical inference at request time, so a cold or missing model
    must never block the app from starting.
    """
    from app import embeddings

    try:
        if embeddings.warm_up(get_settings()):
            logger.info("embedding model warmed at startup")
    except Exception:  # noqa: BLE001 - warmup must not block startup
        logger.warning("embedding warmup skipped", exc_info=True)


_GAP_TOOLS_ENABLED = _gap_tools_enabled()
MCP_INSTRUCTIONS = _build_mcp_instructions(gap_enabled=_GAP_TOOLS_ENABLED)

mcp = FastMCP("quartermaster", instructions=MCP_INSTRUCTIONS)
# Audit per-session tool-call sequences so engagement can be measured (see
# app/mcp_logging.py). Registered here so it wraps every tool defined below.
mcp.add_middleware(ToolCallAuditMiddleware())


@mcp.tool
def list_kits() -> list[dict]:
    """
    List compact V2 discovery metadata for all available kits.

    The response is intentionally signal-dense and short to support
    trait-driven narrowing before loading full kit content.

    :returns: List of compact kit metadata entries.
    """
    return list_catalog_v2()


@mcp.tool
def list_available_traits() -> dict:
    """
    List known trait vocabularies across all kit manifests.

    Use this endpoint to discover supported trait values for
    ``select_kits`` and to identify unknown traits in a project.

    :returns: Aggregated trait keys and normalized vocab lists. The
        ``warnings`` field lists any kits whose applicability manifest
        could not be loaded (and were therefore skipped).
    """
    return list_available_traits_v2()


@mcp.tool
def list_prompts() -> list[dict]:
    """
    List canned MCP usage prompts.

    :returns: Prompt descriptors with ``name``, ``title``, ``intent``,
        and ``prompt_template``.
    """
    return _list_canned_prompts()


@mcp.tool
def get_prompt(name: str) -> dict:
    """
    Return a canned prompt definition by name.

    :param name: Prompt name from ``list_prompts``.
    :returns: Prompt definition object.
    :raises ValueError: If *name* is unknown.
    """
    try:
        return _get_canned_prompt(name)
    except KeyError as exc:
        raise ValueError(f"Prompt not found: {name!r}") from exc


def _register_canned_prompts() -> None:
    """
    Register the canned templates as native FastMCP ``@mcp.prompt``s.

    MCP-spec prompts are *user-initiated* — clients surface them as slash
    commands / prompt galleries. The same templates remain available to
    autonomous agents through the ``list_prompts``/``get_prompt`` tools above;
    :mod:`app.prompts` is the single source of truth for both surfaces.
    """
    from fastmcp.prompts.prompt import Prompt

    for canned in _list_canned_prompts():
        template = canned["prompt_template"]

        # Bind the template per-iteration via a default arg so each prompt
        # function returns its own text (avoids late-binding closure capture).
        def _render(_template: str = template) -> str:
            return _template

        mcp.add_prompt(
            Prompt.from_function(
                _render,
                name=canned["name"],
                title=canned["title"],
                description=canned["intent"],
            )
        )


_register_canned_prompts()


# Gap-filing tools. Defined unconditionally but only registered with the MCP
# when a notification backend is configured (see the registration block
# below), so a self-hosted instance with no backend credentials never
# exposes — or reaches out to — GitHub/GitLab at all.
def check_existing_gap_issue(
    title: str,
    summary: str,
    discovered_traits: list[str] | None = None,
    missing_tools: list[str] | None = None,
    details: str | None = None,
) -> dict:
    """
    Check whether a matching gap issue already exists.

    Use this before ``request_clarification_or_addition`` to avoid
    creating duplicate issues for the same gap.

    :param title: Short request title.
    :param summary: Short problem summary.
    :param discovered_traits: Optional trait labels discovered locally.
    :param missing_tools: Optional missing MCP capability names.
    :param details: Optional free-form details.
    :returns: Match status and existing issue metadata when found.
    :raises ValueError: If required fields are empty or the backend
        search fails.
    """
    return _check_existing_kit_extension_issue(
        title=title,
        summary=summary,
        discovered_traits=discovered_traits,
        missing_tools=missing_tools,
        details=details,
    )


def request_clarification_or_addition(
    title: str,
    summary: str,
    discovered_traits: list[str] | None = None,
    missing_tools: list[str] | None = None,
    details: str | None = None,
) -> dict:
    """
    Submit a clarification or MCP-extension request.

    Requests are materialized as issues on the configured backend (GitHub or
    GitLab). If a matching open issue already exists, no new issue is
    created and that issue is returned as a duplicate.

    :param title: Short request title.
    :param summary: Short problem summary.
    :param discovered_traits: Optional trait labels discovered locally.
    :param missing_tools: Optional missing MCP capability names.
    :param details: Optional free-form details.
    :returns: Created issue metadata or duplicate-match metadata and
        normalized request payload.
    :raises ValueError: If required fields are empty or issue
        creation fails.
    """
    telemetry.record_gap_request()
    return _request_kit_extension(
        title=title,
        summary=summary,
        discovered_traits=discovered_traits,
        missing_tools=missing_tools,
        details=details,
    )


# Only expose the gap tools when a notification backend is configured.
# Otherwise they are not registered at all — the agent never sees them and
# the server makes no outbound calls (suitable for fully self-hosted /
# air-gapped installs).
if _GAP_TOOLS_ENABLED:
    mcp.tool(check_existing_gap_issue)
    mcp.tool(request_clarification_or_addition)


def _user_memory_enabled() -> bool:
    """Return whether per-user memory personalization is enabled.

    Tolerates an incompletely configured environment so it is safe to call
    at import time (see :func:`_gap_tools_enabled`).
    """
    try:
        settings = get_settings()
    except ValidationError:
        return False
    return bool(getattr(settings, "user_memory_enabled", True))


_USER_MEMORY_ENABLED = _user_memory_enabled()


def get_my_memory() -> dict:
    """
    Return the caller's current derived memory profile.

    A small, capped summary of what the caller's own ``resolve_kits``
    history tends to touch (top domains/kits/languages/frameworks). Used
    only as a bounded ranking nudge — never a filter — so it never limits
    which kits a task can surface.

    :returns: The caller's stored profile, or an empty profile (all lists
        empty, ``updated`` null) if none has been derived yet or the caller
        is unauthenticated.
    """
    subject = current_sub()
    if not subject:
        return user_memory.empty_profile()
    profile = user_memory.load_profile(
        get_settings().user_memory_store_path, subject
    )
    return profile or user_memory.empty_profile()


def reset_my_memory() -> dict:
    """
    Clear the caller's derived memory profile.

    Idempotent. The profile is a rebuildable cache derived from the
    caller's own resolve history, so this only resets the *cached*
    familiarity nudge — it does not delete any resolve history itself.

    :returns: ``{"cleared": bool}`` — false when there was nothing to clear
        (including when unauthenticated).
    """
    subject = current_sub()
    if not subject:
        return {"cleared": False}
    cleared = user_memory.clear_profile(
        get_settings().user_memory_store_path, subject
    )
    return {"cleared": cleared}


if _USER_MEMORY_ENABLED:
    mcp.tool(get_my_memory)
    mcp.tool(reset_my_memory)


@mcp.tool
def select_kits(
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    capabilities: list[str] | None = None,
    contexts: list[str] | None = None,
    broaden: bool = False,
    limit: int = 8,
) -> dict:
    """
    Select and rank candidate kits from structured project traits.

    Use this as the primary V2 discovery entry-point. Call again with
    ``broaden=True`` when ``broadening_recommended`` is true.

    :param languages: Language hints, e.g. ``["python"]``.
    :param frameworks: Framework hints, e.g. ``["fastapi"]``.
    :param capabilities: Capability hints, e.g. ``["auth"]``.
    :param contexts: Context hints, e.g. ``["docs"]``.
    :param broaden: Lower selection threshold for recall recovery.
    :param limit: Maximum candidates to return (bounded internally).
    :returns: Candidate list plus confidence and coverage diagnostics. The
        ``warnings`` field lists any kits whose applicability manifest could
        not be loaded (and were therefore skipped during ranking).
    """
    return select_kits_v2(
        languages=languages,
        frameworks=frameworks,
        capabilities=capabilities,
        contexts=contexts,
        broaden=broaden,
        limit=limit,
    )


def _settings_or_none() -> Any:
    """Return the Settings singleton, or ``None`` if config is incomplete."""
    try:
        return get_settings()
    except ValidationError:
        return None


def _sampling_memory_hint(settings: Any) -> str:
    """Return an advisory memory hint for the sampling prompt, or ``""``.

    Best-effort: no authenticated caller, memory disabled, or any failure
    all return ``""`` so personalization can never block sampling.
    """
    subject = current_sub()
    if not subject:
        return ""
    if settings is not None and not getattr(
        settings, "user_memory_enabled", True
    ):
        return ""
    path = getattr(settings, "user_memory_store_path", None)
    if path is None:
        return ""
    try:
        profile = user_memory.load_profile(path, subject)
        return profile_hint(profile)
    except Exception as exc:  # hint generation must never break sampling
        logger.warning("memory hint generation failed: %s", exc)
        return ""


async def _infer_via_sampling(
    task: str, ctx: Context, settings: Any
) -> Any:
    """
    Infer traits via MCP sampling, or ``None`` to fall back to the chain.

    Returns ``None`` (no sampling) when disabled in settings, when the client
    does not advertise the sampling capability, or when the sample yields no
    in-vocabulary traits. Never raises — the engine swallows its own failures.

    :param task: The free-text task description.
    :param ctx: The active FastMCP request context.
    :param settings: The Settings singleton, or ``None`` when unconfigured.
    :returns: ``InferredTraits`` from sampling, or ``None``.
    """
    if settings is not None and not getattr(settings, "sampling_enabled", True):
        return None
    if not client_supports_sampling(ctx):
        return None
    vocab = await asyncio.to_thread(load_vocabulary)
    hint = await asyncio.to_thread(_sampling_memory_hint, settings)
    traits = await SamplingTraitEngine().infer_async(
        task, vocab, ctx, hint=hint
    )
    if traits is not None and traits.has_any():
        return traits
    return None


async def _resolve_once(
    task: str,
    *,
    ctx: Context | None,
    settings: Any,
    broaden: bool,
    limit: int,
    max_sections_per_kit: int,
) -> dict:
    """
    Run one resolution: sampling inference (if available) + sync assembly.

    Sampling is preferred when the client supports it; otherwise the resolver
    runs its own deterministic chain. The synchronous resolver (and its
    blocking LLM/embedding/file I/O) runs in a worker thread so this async
    path never stalls the event loop.
    """
    pre_inferred = None
    section_ranker = None
    if ctx is not None:
        pre_inferred = await _infer_via_sampling(task, ctx, settings)
        if pre_inferred is not None:
            section_ranker = await asyncio.to_thread(build_ranker)

    return await asyncio.to_thread(
        _resolve_kits,
        task=task,
        broaden=broaden,
        limit=limit,
        max_sections_per_kit=max_sections_per_kit,
        pre_inferred=pre_inferred,
        section_ranker=section_ranker,
    )


_EMPTY_TASK_ELICIT = (
    "What do you want to build or change? Describe the task in a sentence or "
    "two so I can recommend the right instruction kits (mention the language, "
    "framework, or capability if you know them)."
)
_LOW_CONFIDENCE_ELICIT = (
    "I couldn't confidently match kits to that request. Which language, "
    "framework, or capability does it involve? Add any detail that would "
    "narrow it down."
)


async def _elicit_text(ctx: Context | None, message: str) -> str | None:
    """
    Ask the user a free-text question via MCP elicitation.

    :returns: The user's text, or ``None`` when there is no context, they
        decline/cancel, or the call fails (elicitation must never break
        resolution).
    """
    if ctx is None:
        return None
    try:
        # FastMCP wraps a primitive ``str`` response in a single-field object
        # and unwraps it back to a str on ``.data``. (Its @overload set has a
        # known resolution quirk for primitives, hence the type-ignore.)
        result = await ctx.elicit(
            message,
            response_type=str,  # type: ignore[arg-type]
        )
    except Exception as exc:  # elicitation must never break resolution
        logger.warning("elicitation failed: %s", exc)
        return None
    # AcceptedElicitation carries ``.data``; Declined/Cancelled do not.
    data = getattr(result, "data", None)
    if data is None:
        return None
    text = str(data).strip()
    return text or None


def _is_low_confidence(result: dict, settings: Any) -> bool:
    """
    Return whether a resolve result is too weak to return without clarifying.

    Low confidence means either nothing was inferred at all, or the scorer
    recommended broadening *and* confidence fell below the configured floor.
    """
    traits = result.get("inferred_traits", {})
    has_traits = any(
        traits.get(key)
        for key in ("languages", "frameworks", "capabilities", "contexts")
    )
    if not has_traits:
        return True
    threshold = 0.25
    if settings is not None:
        threshold = getattr(
            settings, "resolve_elicit_min_confidence", threshold
        )
    return bool(result.get("broadening_recommended")) and (
        result.get("confidence", 1.0) < threshold
    )


_REPORT_INSTRUCTION = (
    "Quartermaster diagnostics are active. After completing this task, "
    "present the user with a **Quartermaster Insights report** containing "
    "the following sections:\n"
    "1. Traits inferred — list the languages, frameworks, capabilities, and "
    "contexts that were detected from the task description, and note which "
    "inference engine (sampling / LLM / embedding / lexical) identified them. "
    "Mention if you were asked to clarify the task before kits could be "
    "matched.\n"
    "2. Kits selected — for each kit loaded, name it and summarise the key "
    "guidance it provided (invariants, required patterns, prohibited "
    "approaches).\n"
    "3. Impact on this task — for each significant implementation decision, "
    "state whether and how a kit's guidance shaped it. Be explicit (e.g. "
    "\"Used PKCE flow because module-auth-oidc requires it\"). If a decision "
    "was not influenced by any kit, say so — gaps in coverage are useful data "
    "for evaluating Quartermaster.\n"
    "Keep the report concise but honest. Its purpose is to let the user "
    "assess whether Quartermaster's guidance improved the outcome."
)


def _build_diagnostics(result: dict, *, clarification_used: bool) -> dict:
    """
    Assemble the ``_diagnostics`` metadata block from a resolve *result*.

    All values are already present in the resolver's return dict; this only
    reshapes them for human evaluation and appends the report directive.

    :param result: The finalised resolve result (post-elicitation).
    :param clarification_used: Whether an elicitation round refined the task.
    :returns: The diagnostics block to attach under ``result["_diagnostics"]``.
    """
    traits = result.get("inferred_traits", {})
    return {
        "engine": result.get("engine"),
        "clarification_used": clarification_used,
        "trait_provenance": traits.get("provenance", []),
        "kit_scores": [
            {
                "name": kit["name"],
                "score": kit["score"],
                "confidence": kit["confidence"],
                "reasons": kit["reasons"],
            }
            for kit in result.get("kits", [])
        ],
        "coverage": result.get("coverage"),
        "selection_confidence": result.get("confidence"),
        "report_instruction": _REPORT_INSTRUCTION,
    }


@mcp.tool
async def resolve_kits(
    task: str,
    broaden: bool = False,
    limit: int = 8,
    max_sections_per_kit: int = 8,
    include_diagnostics: bool = False,
    ctx: Context | None = None,
) -> dict:
    """
    Resolve a free-text task to ranked kits with core content inlined.

    **Start here for kit discovery.** This is the default, one-shot path:
    instead of running the discovery loop (``list_available_traits`` →
    ``select_kits`` → ``explain_kit_candidate`` → ``get_kit_outline`` →
    ``get_kit``) yourself, describe the task and the server infers the
    traits, ranks kits, and returns the recommendation with each kit's
    ``always_load`` sections already inlined. Other relevant section ids are
    returned under ``fetch_on_demand`` to pull later via
    ``get_kit(name, sections=[…])``.

    Trait inference prefers MCP **sampling** (the connecting client's own LLM)
    when the client supports it, then degrades to a configured HTTP LLM, local
    embeddings, and a lexical floor; the ``engine`` field reports which
    produced the result. Use ``select_kits`` directly when you have already
    mapped the task to explicit traits.

    :param task: Natural-language description of the work to be done.
    :param broaden: Lower the selection threshold to widen recall.
    :param limit: Maximum number of candidate kits to return.
    :param max_sections_per_kit: Cap on non-``always_load`` sections offered
        per kit for on-demand fetching.
    :param include_diagnostics: When true, attach a ``_diagnostics`` block
        (inference engine, trait provenance, per-kit scores, coverage, whether
        a clarification round ran) plus a directive asking the agent to report
        Quartermaster's impact after the task. Off by default.
    :returns: ``{engine, inferred_traits, confidence, coverage,
        broadening_recommended, kits, warnings}``; each kit carries
        ``sections``, ``always_load_markdown`` and ``fetch_on_demand``. When
        *include_diagnostics* is set, also ``_diagnostics``.
    :raises ValueError: If *task* is empty and the client cannot be asked to
        clarify (no elicitation support).
    """
    settings = _settings_or_none()
    elicitation_on = settings is None or getattr(
        settings, "elicitation_enabled", True
    )
    can_elicit = (
        ctx is not None
        and elicitation_on
        and client_supports_elicitation(ctx)
    )

    task = (task or "").strip()
    # Disambiguate an empty task up front rather than failing outright.
    if not task and can_elicit:
        clarified = await _elicit_text(ctx, _EMPTY_TASK_ELICIT)
        if clarified:
            task = clarified
    if not task:
        # No task and no way (or no willingness) to clarify: preserve the
        # resolver's empty-task ValueError contract.
        return await asyncio.to_thread(
            _resolve_kits,
            task=task,
            broaden=broaden,
            limit=limit,
            max_sections_per_kit=max_sections_per_kit,
        )

    result = await _resolve_once(
        task,
        ctx=ctx,
        settings=settings,
        broaden=broaden,
        limit=limit,
        max_sections_per_kit=max_sections_per_kit,
    )

    # One clarification round on a weak match: ask for detail, then re-resolve
    # with the enriched task. Declining keeps the best-effort first result.
    clarification_used = False
    if can_elicit and _is_low_confidence(result, settings):
        extra = await _elicit_text(ctx, _LOW_CONFIDENCE_ELICIT)
        if extra:
            clarification_used = True
            result = await _resolve_once(
                f"{task}\n{extra}",
                ctx=ctx,
                settings=settings,
                broaden=broaden,
                limit=limit,
                max_sections_per_kit=max_sections_per_kit,
            )

    if include_diagnostics:
        result["_diagnostics"] = _build_diagnostics(
            result, clarification_used=clarification_used
        )

    return result


@mcp.tool
def explain_kit_candidate(
    name: str,
    languages: list[str] | None = None,
    frameworks: list[str] | None = None,
    capabilities: list[str] | None = None,
    contexts: list[str] | None = None,
) -> dict:
    """
    Explain applicability for one specific kit against project traits.

    Call this after ``select_kits`` for the shortlist only.

    :param name: Kit name to evaluate.
    :param languages: Language hints.
    :param frameworks: Framework hints.
    :param capabilities: Capability hints.
    :param contexts: Context hints.
    :returns: Structured explanation with score and constraint details.
    :raises ValueError: If *name* does not match any known kit.
    """
    try:
        return explain_kit_v2(
            name=name,
            languages=languages,
            frameworks=frameworks,
            capabilities=capabilities,
            contexts=contexts,
        )
    except KitNotFoundError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool
def get_kit_outline(name: str, version: str | None = None) -> dict:
    """
    Return a cheap section map for a kit before loading its content.

    Read this first to see which sections a kit contains, then call
    ``get_kit`` with ``sections=[…]`` to pull only the sections the
    current step needs. Sections flagged ``always_load`` hold the kit's
    core invariants and should usually be loaded first.

    :param name: Kit name, e.g. ``module-database-postgresql``.
    :param version: Major version string, e.g. ``"v1"``.  When omitted
        the latest available version is used.
    :returns: ``{name, version, summary, sections}`` where each section
        is ``{id, title, gloss, always_load, bytes}``.
    :raises ValueError: If *name* does not match any known kit, or if
        *version* is not available for that kit.
    """
    try:
        return read_kit_outline(name, version)
    except KitNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except KitVersionNotFoundError as exc:
        raise ValueError(str(exc)) from exc


@mcp.tool
def get_kit(
    name: str,
    version: str | None = None,
    sections: list[str] | None = None,
) -> str:
    """
    Return instruction content for the named kit.

    Load the kit identified by *name* (as returned by ``list_kits``)
    and return its Markdown text.  Pass this text to the agent in the
    system context or as a file reference to activate the kit's
    guard-rails for the current session.

    Prefer loading only what the current step needs: call
    ``get_kit_outline`` first, then pass *sections* to pull just those
    sections. Omit *sections* to get the complete instructions.

    :param name: Kit name, e.g. ``stack-fastapi-vuetify`` or
        ``module-auth-local``.
    :param version: Major version string, e.g. ``"v1"``.  When
        omitted the latest available version is returned.
    :param sections: Optional section ids from ``get_kit_outline``.
        When omitted, the full instructions are returned.
    :returns: UTF-8 Markdown for the requested sections (or the whole
        kit when *sections* is omitted).
    :raises ValueError: If *name* does not match any known kit, if
        *version* is not available, or if a section id is unknown.
    """
    try:
        markdown = read_kit(name, version, sections)
    except KitNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except KitVersionNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except KitSectionNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    disposition = "sections" if sections else "full"
    tokens = count_tokens(markdown)
    telemetry.record_kit_delivery(
        kit=name,
        disposition=disposition,
        tokens=tokens,
        section_ids=sections or [],
    )
    local_store.record_delivery(
        kit=name, disposition=disposition, tokens=tokens
    )
    return markdown


@mcp.tool
def list_kit_versions(name: str) -> list[str]:
    """
    List the available major versions of a single instruction kit.

    :param name: Kit name as returned by ``list_kits``.
    :returns: List of major version strings, oldest first, e.g.
        ``["v1", "v2"]``.
    :raises ValueError: If *name* does not match any known kit.
    """
    kits = {k.name: k for k in list_all_kits()}
    if name not in kits:
        raise ValueError(f"Kit not found: {name!r}")
    return kits[name].versions


@mcp.tool
def compare_kit_versions(
    name: str,
    from_version: str,
    to_version: str,
) -> dict:
    """
    Summarise changes between two versions of an instruction kit.

    Reads the kit's ``CHANGELOG.md`` and returns all changelog
    sections that fall strictly after *from_version* and up to and
    including *to_version*.  Both major versions (e.g. ``"v1"`` →
    ``"v2"``) and minor/patch releases (e.g. ``"v1.0.0"`` →
    ``"v1.2.0"``) are supported.  The argument order does not matter —
    the lower version is always used as the exclusive lower bound.

    .. warning::

        When ``user_facing_warning`` is ``True``, the changes contain
        modifications that may affect **end-users** of any project
        built with this kit (for example: changes to authentication
        flows, API shapes, URL routes, passwords, tokens, sessions, or
        database schemas).  Review carefully before upgrading.

    :param name: Kit name as returned by ``list_kits``.
    :param from_version: One end of the version range (exclusive),
        e.g. ``"v1.0.0"`` or ``"v1"``.
    :param to_version: Other end of the version range (inclusive),
        e.g. ``"v2.0.0"`` or ``"v2"``.
    :returns: Dict with keys:

        ``changes``
            List of ``{"version": str, "summary": str}`` dicts for
            each changelog section in the requested range, ordered
            from oldest to newest.

        ``user_facing_warning``
            ``True`` when any change section contains keywords
            suggesting an impact on end-users of projects that use
            this kit.

    :raises ValueError: If *name* does not match any known kit, or if
        the kit has no ``CHANGELOG.md``.
    """
    try:
        return _compare_kit_versions(name, from_version, to_version)
    except KitNotFoundError as exc:
        raise ValueError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise ValueError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Outer FastAPI application
# ---------------------------------------------------------------------------
#
# The public well-known / health handlers are defined at module level and
# wired into the app inside :func:`create_app`.  Keeping construction in an
# application factory (per the module-fastapi kit) lets tests build isolated
# app instances and gives later phases a single place to register the
# ``/api`` admin routers and the ``/dav`` WebDAV mount.


async def health() -> dict:
    """
    Liveness probe.

    No authentication is required.

    :returns: ``{"status": "ok"}``
    """
    return {"status": "ok"}


async def metrics_endpoint() -> Response:
    """
    Prometheus pull endpoint.

    Serves the OpenTelemetry metrics in Prometheus exposition format. Mounted
    only when ``QM_METRICS_PROMETHEUS_ENABLED`` is set and the Prometheus
    reader is available. Secured by app-token HTTP Basic in
    :class:`~app.auth.JWTAuthMiddleware` unless ``QM_METRICS_ALLOW_ANONYMOUS``
    is set.

    :returns: Prometheus exposition response.
    """
    payload, content_type = telemetry.prometheus_exposition()
    return Response(content=payload, media_type=content_type)


async def oauth_protected_resource_metadata() -> JSONResponse:
    """
    OAuth 2.0 Protected Resource Metadata (RFC 9728).

    Advertises the authorization server(s) that can issue tokens for
    this resource.  OAuth-aware clients (e.g. VS Code MCP integration)
    fetch this document after receiving a ``401`` with a
    ``WWW-Authenticate`` header pointing here, then initiate an
    authorization-code + PKCE flow automatically.

    No authentication is required to fetch this document.

    :returns: RFC 9728-compliant JSON metadata document.
    """
    settings = get_settings()
    resource = settings.server_origin
    logger.debug("oauth-protected-resource (root): resource=%s", resource)
    return JSONResponse(
        {
            "resource": resource,
            "authorization_servers": [settings.keycloak_issuer],
            "bearer_methods_supported": ["header"],
            "scopes_supported": settings.oauth_scopes,
        },
        headers={"Cache-Control": "no-store"},
    )


async def oauth_protected_resource_metadata_path(path: str) -> JSONResponse:
    """
    RFC 9728 path-specific Protected Resource Metadata.

    Clients that discover authorization requirements for a resource at
    ``{origin}/{path}`` fetch
    ``{origin}/.well-known/oauth-protected-resource/{path}`` per
    RFC 9728 §3.  Return the same authorization-server advertisement
    as the root well-known document.

    No authentication is required to fetch this document.

    :param path: Resource path appended by the client (e.g. ``kits/mcp``).
    :returns: RFC 9728-compliant JSON metadata document.
    """
    settings = get_settings()
    resource = f"{settings.server_origin}/{path}"
    logger.debug(
        "oauth-protected-resource (path-specific): path=%r resource=%s",
        path,
        resource,
    )
    return JSONResponse(
        {
            "resource": resource,
            "authorization_servers": [settings.keycloak_issuer],
            "bearer_methods_supported": ["header"],
            "scopes_supported": settings.oauth_scopes,
        },
        headers={"Cache-Control": "no-store"},
    )


async def oauth_authorization_server_metadata() -> JSONResponse:
    """
    OAuth 2.0 Authorization Server Metadata (RFC 8414).

    Some OAuth clients (including VS Code's MCP integration) discover
    the authorization server by fetching this document from the
    resource server's origin before following the RFC 9728 chain.
    This document advertises Keycloak's endpoints directly so that
    clients redirect the browser to Keycloak without any proxy.

    No authentication is required to fetch this document.

    :returns: RFC 8414-compliant JSON metadata document.
    """
    settings = get_settings()
    return JSONResponse(
        {
            # issuer MUST match this server's origin per RFC 8414 §3.3,
            # not the Keycloak URL.  Keycloak's URL is only used internally
            # for JWT validation (keycloak_issuer) and as the endpoint base.
            "issuer": settings.server_origin,
            "authorization_endpoint": settings.authorization_endpoint,
            "token_endpoint": settings.token_endpoint,
            "jwks_uri": settings.jwks_url,
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
            ],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
            "scopes_supported": settings.oauth_scopes,
        },
        headers={"Cache-Control": "no-store"},
    )


# Map kit-domain exceptions to HTTP status codes for the /api routers.
# (HTTPException would couple the service layer to FastAPI; instead the
# thin routers let domain exceptions propagate and we translate here.)
_EXCEPTION_STATUS: dict[type[Exception], int] = {
    EditorRequiredError: 403,
    PrivateKitAccessError: 404,
    KitNotFoundError: 404,
    KitVersionNotFoundError: 404,
    KitSectionNotFoundError: 404,
    KitLayerNotFoundError: 404,
    KitConflictError: 409,
    KitValidationError: 422,
    KitPathError: 400,
    KitLayerReadonlyError: 403,
}


def _register_exception_handlers(application: FastAPI) -> None:
    """
    Register handlers translating kit-domain exceptions to HTTP errors.

    :param application: The FastAPI app to attach handlers to.
    """

    def _make_handler(
        code: int,
    ) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
        async def _handler(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(
                status_code=code, content={"detail": str(exc)}
            )

        return _handler

    for exc_type, code in _EXCEPTION_STATUS.items():
        application.add_exception_handler(exc_type, _make_handler(code))


def create_app() -> FastAPI:
    """
    Build and return the outer FastAPI application.

    Wires the public health/well-known endpoints and the ``/api`` admin
    routers, mounts the FastMCP streamable-HTTP app at ``/kits/mcp``, and
    applies :class:`~app.auth.JWTAuthMiddleware` last so it wraps every
    route.

    :returns: Fully assembled FastAPI application.
    """
    # Configure OpenTelemetry metrics + traces once. Tolerant of an
    # incompletely configured environment (e.g. during test collection),
    # mirroring _gap_tools_enabled.
    serve_metrics = False
    try:
        settings = get_settings()
        telemetry.init_telemetry(settings)
        serve_metrics = (
            settings.metrics_prometheus_enabled
            and telemetry.prometheus_enabled()
        )
    except ValidationError:
        pass

    mcp_app = mcp.http_app(path="/mcp")

    @contextlib.asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Init the local metrics store, warm embeddings, run FastMCP lifespan.

        Composed (not replacing) so the OTEL-independent dashboard store is
        opened once at startup; a failure here never blocks the app (init is
        itself best-effort). The embedding warmup is offloaded to a thread so
        the event loop stays responsive, but startup completes only after it
        returns — so k8s marks the pod Ready only once the first
        ``resolve_kits`` will be served warm, not cold.
        """
        try:
            local_store.init(get_settings())
        except Exception:  # noqa: BLE001 - metrics must not block startup
            logger.warning("local metrics store init skipped", exc_info=True)
        await asyncio.to_thread(_warm_embeddings)
        async with mcp_app.lifespan(app):
            yield

    # Swagger docs are enabled so the vendor media-type contract is
    # discoverable. They sit behind the auth + User-Agent middleware like
    # the rest of the app (not in the public-path allowlist).
    application = FastAPI(
        title="Quartermaster MCP",
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
        lifespan=_lifespan,
    )

    # Health probes (module-observability-healthz). /health is kept as a
    # back-compat liveness alias for existing Docker/Traefik healthchecks.
    application.add_api_route("/health", health, methods=["GET"])
    application.add_api_route("/livez", health_probes.livez, methods=["GET"])
    application.add_api_route("/readyz", health_probes.readyz, methods=["GET"])
    application.add_api_route(
        "/healthz", health_probes.healthz, methods=["GET"]
    )
    application.add_api_route(
        "/.well-known/oauth-protected-resource",
        oauth_protected_resource_metadata,
        methods=["GET"],
    )
    application.add_api_route(
        "/.well-known/oauth-protected-resource/{path:path}",
        oauth_protected_resource_metadata_path,
        methods=["GET"],
    )
    application.add_api_route(
        "/.well-known/oauth-authorization-server",
        oauth_authorization_server_metadata,
        methods=["GET"],
    )

    # /api admin + integration + client-registration routers (protected
    # by the JWT + User-Agent middleware).
    # kits_layers must be registered before kits_admin so that the more-specific
    # /api/kits/layers/* paths are matched before /api/kits/{name}.
    application.include_router(kits_layers.router)
    application.include_router(kits_admin.router)
    application.include_router(integration.router)
    application.include_router(clients.router)
    application.include_router(app_tokens.router)
    application.include_router(metrics_router.router)
    application.include_router(me_router.router)
    application.include_router(roles_router.router)
    application.include_router(private_kits_router.router)

    # Dev-only auth bypass: the token-minting router is imported and mounted
    # ONLY when explicitly enabled, so /auth/dev/* is a plain 404 in
    # production. Read from the environment directly so app construction does
    # not require a fully-validated Settings object.
    if os.environ.get("QM_DEV_AUTH_ENABLED", "").lower() in (
        "1",
        "true",
        "yes",
    ):
        from app.routers import auth_dev

        application.include_router(auth_dev.router)
        logger.warning(
            "DEV AUTH ENABLED: /auth/dev/* mounted. Never set "
            "QM_DEV_AUTH_ENABLED in production."
        )

    _register_exception_handlers(application)

    # Wrap the MCP mount so the authenticated caller's identity (stashed on
    # scope["state"] by JWTAuthMiddleware) is bound to context variables in the
    # same task the tool runs in — the only reliable way to make identity
    # visible inside @mcp.tool functions (see app.mcp_identity).
    application.mount("/kits", MCPIdentityASGI(mcp_app))

    # WebDAV authoring endpoint over the kit catalog (Basic + app token,
    # enforced by JWTAuthMiddleware). Writes land on kits_root and are
    # visible to the MCP immediately (kit reads are uncached).
    mount_dav(application)

    # Prometheus pull endpoint. Mounted only when this app enables it and the
    # reader installed (the telemetry extra is present). Added before the SPA
    # fallback so it is never shadowed; secured (or left anonymous) by
    # JWTAuthMiddleware per QM_METRICS_ALLOW_ANONYMOUS.
    if serve_metrics:
        application.add_api_route(
            "/metrics", metrics_endpoint, methods=["GET"]
        )

    # Serve the built SPA + /config.js (no-op when there is no build). The
    # SPA fallback route is added last so it never shadows /api, /kits, the
    # well-known docs, or Swagger.
    mount_webui(application)

    # Middleware ORDER MATTERS: Starlette applies middleware LIFO, so the
    # LAST add_middleware call sits OUTERMOST and runs first on the way in.
    # Do not reorder (module-http-middleware-hardening). Outermost -> innermost:
    #   RequestLogging   - sets the correlation ID first so every inner log
    #                      record (incl. auth) shares it; logs every response.
    #   VersionHeader    - stamps X-Quartermaster-Version.
    #   SecurityHeaders  - sets the 3 security headers; sits outside auth so
    #                      even 401/403 responses carry them.
    #   UserAgent        - rejects unregistered non-browser clients before any
    #                      token work (clear pointer to the registration route).
    #   JWTAuth          - validates the bearer token (innermost).
    application.add_middleware(JWTAuthMiddleware)
    application.add_middleware(UserAgentMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        VersionHeaderMiddleware, version=app_version()
    )
    application.add_middleware(RequestLoggingMiddleware)
    return application


app = create_app()
