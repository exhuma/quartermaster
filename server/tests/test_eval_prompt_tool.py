"""
Tests for the eval agent surfaces: the bundled ``catalog_evaluation`` prompt
and the ``evaluate_catalog`` MCP tool. The prompt must be domain-neutral (it
ships in a domain-agnostic server); the tool must be registered.
"""

from __future__ import annotations

import anyio

from app.prompts import get_canned_prompt, list_canned_prompts

# Domain-specific vocabulary that must NOT appear in a domain-agnostic runbook.
# ("python" is allowed: it names the `python -m app.eval` interpreter command.)
_DOMAIN_WORDS = ("fastapi", "vuetify", "typescript", "javascript", "oidc")


def test_catalog_evaluation_prompt_registered() -> None:
    names = [p["name"] for p in list_canned_prompts()]
    assert "catalog_evaluation" in names


def test_catalog_evaluation_prompt_is_domain_neutral() -> None:
    body = get_canned_prompt("catalog_evaluation")["prompt_template"].lower()
    assert body  # non-empty
    leaked = [w for w in _DOMAIN_WORDS if w in body]
    assert leaked == [], f"prompt leaks domain vocabulary: {leaked}"
    # It should mention the eval entry points.
    assert "eval-cases.yaml" in body
    assert "--baseline" in body


def test_evaluate_catalog_tool_registered() -> None:
    from app.main import mcp

    async def _get() -> str:
        return (await mcp.get_tool("evaluate_catalog")).name

    assert anyio.run(_get) == "evaluate_catalog"
