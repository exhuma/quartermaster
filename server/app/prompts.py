"""Canned prompt templates exposed through MCP tools."""

from __future__ import annotations

_PROMPTS: list[dict[str, str]] = [
    {
        "name": "legacy_assessment",
        "title": "Legacy Project Diagnostic",
        "intent": (
            "Assess an aging codebase and identify high-value "
            "applicable kits."
        ),
        "prompt_template": (
            "Analyze this legacy project and infer traits from the "
            "repository. "
            "Use the instruction MCP to select candidate kits, broaden "
            "if needed, "
            "and explain top recommendations with migration risk."
        ),
    },
    {
        "name": "bootstrap_sequence",
        "title": "Project Bootstrap Kit Sequence",
        "intent": "Build a staged kit loading sequence for a project setup.",
        "prompt_template": (
            "Given this project context, infer stack traits and produce "
            "a recommended "
            "kit sequence with dependencies, ordering, and rationale."
        ),
    },
    {
        "name": "capability_extension",
        "title": "Add Capability To Existing Project",
        "intent": (
            "Add a new capability while preserving compatibility with "
            "current stack."
        ),
        "prompt_template": (
            "Identify what is missing for the target capability, select "
            "relevant kits, "
            "flag conflicts with existing traits, and propose an "
            "implementation plan."
        ),
    },
    {
        "name": "tech_debt_modernization",
        "title": "Tech Debt Modernization Priority",
        "intent": (
            "Prioritize modernization work with kit-guided adoption "
            "steps."
        ),
        "prompt_template": (
            "Assess technical debt hotspots, map them to applicable "
            "kits, and rank "
            "changes by impact, effort, and rollout risk."
        ),
    },
]


def list_canned_prompts() -> list[dict[str, str]]:
    """Return all canned prompt definitions."""
    return list(_PROMPTS)


def get_canned_prompt(name: str) -> dict[str, str]:
    """
    Return a canned prompt by name.

    :raises KeyError: If *name* does not match a canned prompt.
    """
    for prompt in _PROMPTS:
        if prompt["name"] == name:
            return dict(prompt)
    raise KeyError(name)
