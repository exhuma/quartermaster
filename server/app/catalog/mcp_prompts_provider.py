"""Native FastMCP ``Provider`` exposing the prompts catalog as MCP prompts.

MCP-spec prompts are *user-invoked* (clients surface them as slash commands
or a prompt gallery), distinct from the ``list_catalog_prompts`` /
``get_catalog_prompt`` MCP *tools* in ``app.main`` that an autonomous agent
calls itself. Both surfaces read the same catalog
(:mod:`app.prompt_catalog`), live, on every call — there is no cache, so a
write via REST/WebDAV or the catalog MCP tools is visible on the very next
list/get, without a server restart (mirrors "kit reads are uncached").

Per FastMCP's precedence rule, statically decorator-registered prompts (the
canned templates in ``app.prompts``, registered via
``app.main._register_canned_prompts``) always win over a provider-sourced
prompt of the same name. The prompts-catalog write path enforces the
corresponding name-collision guard so a catalog prompt can never be silently
shadowed and unreachable (see
:func:`app.services.prompt_catalog_service._static_prompt_names`).
"""

from __future__ import annotations

from collections.abc import Sequence

from fastmcp.prompts.prompt import Prompt

from app.prompt_catalog import (
    PromptNotFoundError,
    PromptValidationError,
    list_all_prompts,
    read_prompt,
)

try:  # pragma: no cover - import path is stable in the pinned fastmcp version
    from fastmcp.server.providers.base import Provider
except ImportError:  # pragma: no cover
    from fastmcp.server.providers import Provider  # type: ignore[no-redef]


class PromptsCatalogProvider(Provider):
    """Sources MCP prompts dynamically from the prompts catalog.

    Visibility is per-caller: the shared catalog layers plus the calling
    subject's own private overlay (resolved from the identity contextvar via
    :mod:`app.prompt_catalog`'s ``CTX_SUBJECT`` default — no explicit
    ``subject`` argument is threaded through here).
    """

    async def _list_prompts(self) -> Sequence[Prompt]:
        """Return every visible catalog prompt as a FastMCP ``Prompt``.

        Broken (malformed frontmatter) entries are skipped — they are
        surfaced for fixing via the REST/WebDAV/MCP-tool listing surfaces
        instead, not served as content.
        """
        prompts: list[Prompt] = []
        for info in list_all_prompts():
            if info.broken:
                continue
            try:
                prompts.append(_to_mcp_prompt(info.name))
            except (PromptNotFoundError, PromptValidationError):
                # Raced with a concurrent delete/edit between the listing
                # scan and the read below; drop it from this listing rather
                # than fail the whole call.
                continue
        return prompts

    async def _get_prompt(
        self, name: str, version: object = None
    ) -> Prompt | None:
        """Return a single prompt by name, or ``None`` when not found.

        ``None`` tells FastMCP "I don't have it" so it can keep searching
        other providers, per :class:`~fastmcp.server.providers.base.Provider`
        semantics — this covers both a genuinely unknown name and a broken
        (malformed frontmatter) one.
        """
        try:
            return _to_mcp_prompt(name)
        except (PromptNotFoundError, PromptValidationError):
            return None


def _to_mcp_prompt(name: str) -> Prompt:
    """Fetch *name*'s live content and wrap it as a FastMCP ``Prompt``.

    :raises PromptNotFoundError: If *name* does not exist for the caller.
    :raises PromptValidationError: If the prompt's frontmatter is malformed.
    """
    detail = read_prompt(name)

    # Bind the body per-call via a default arg so each Prompt returns its own
    # text (avoids late-binding closure capture), mirroring
    # app.main._register_canned_prompts.
    def _render(_body: str = detail.body) -> str:
        return _body

    return Prompt.from_function(
        _render,
        name=detail.name,
        title=detail.title or None,
        description=detail.description or None,
    )
