"""Canned prompt templates exposed through MCP tools.

Each entry keeps its ``name``/``title``/``intent`` metadata inline (small,
structured, logic-adjacent) but sources its ``prompt_template`` body from a raw
markdown file bundled under ``app/assets/prompts/`` and loaded via
:func:`app.templating.render_asset`. The public accessors below assemble the
same ``{name, title, intent, prompt_template}`` dict the rest of the app
expects, so callers are unaffected by where the body text lives.
"""

from __future__ import annotations

from app.templating import render_asset
from app.version import app_channel

# Prompt bodies reference the published container image at its default channel;
# rewrite that tag to the channel this build actually advances so a beta/rc/
# stable image hands out its own image tag. A no-op on the default channel.
_DEFAULT_IMAGE = "ghcr.io/exhuma/quartermaster:alpha"
_IMAGE_BASE = "ghcr.io/exhuma/quartermaster"


def _bake_image_channel(body: str) -> str:
    channel = app_channel()
    if channel == "alpha":
        return body
    return body.replace(_DEFAULT_IMAGE, f"{_IMAGE_BASE}:{channel}")

# Registry of canned prompts. ``template_file`` is a basename under
# ``app/assets/prompts/``; the body is loaded on access.
_PROMPTS: list[dict[str, str]] = [
    {
        "name": "greet",
        "title": "Meet Quartermaster",
        "intent": (
            "Introduce Quartermaster to a coding agent connecting for the "
            "first time: what it is, how to load kits, and where to go next."
        ),
        "template_file": "greet.md",
    },
    {
        "name": "integrate_project",
        "title": "Integrate Quartermaster Into This Project",
        "intent": (
            "Wire Quartermaster into the host project's agent-instruction "
            "files so future agents know to use it for kit discovery."
        ),
        "template_file": "integrate-project.md",
    },
    {
        "name": "trait_selection_bootstrap",
        "title": "Quartermaster Trait-Selection Bootstrap",
        "intent": (
            "How to drive Quartermaster's own trait-selection workflow "
            "efficiently and correctly. This is guidance for *using* "
            "Quartermaster to find kits — not implementation work on the "
            "target project."
        ),
        "template_file": "trait-selection-bootstrap.md",
    },
    {
        "name": "legacy_assessment",
        "title": "Legacy Project Diagnostic",
        "intent": (
            "Assess an aging codebase and identify high-value applicable kits."
        ),
        "template_file": "legacy-assessment.md",
    },
    {
        "name": "bootstrap_sequence",
        "title": "Project Bootstrap Kit Sequence",
        "intent": "Build a staged kit loading sequence for a project setup.",
        "template_file": "bootstrap-sequence.md",
    },
    {
        "name": "capability_extension",
        "title": "Add Capability To Existing Project",
        "intent": (
            "Add a new capability while preserving compatibility with "
            "current stack."
        ),
        "template_file": "capability-extension.md",
    },
    {
        "name": "tech_debt_modernization",
        "title": "Tech Debt Modernization Priority",
        "intent": (
            "Prioritize modernization work with kit-guided adoption steps."
        ),
        "template_file": "tech-debt-modernization.md",
    },
    {
        "name": "bootstrap_project_skills",
        "title": "Bootstrap Project Skills",
        "intent": (
            "Build a compact `.skills/` knowledge base so future coding "
            "agents work efficiently without repeatedly exploring the repo."
        ),
        "template_file": "bootstrap-skills.md",
    },
    {
        "name": "audit_project_skills",
        "title": "Audit Project Skills",
        "intent": (
            "Review the `.skills/` directory for knowledge gaps, staleness, "
            "and duplication that would force unnecessary repo exploration."
        ),
        "template_file": "audit-project-skills.md",
    },
    {
        "name": "maintain_project_skills",
        "title": "Maintain Project Skills",
        "intent": (
            "Update the `.skills/` directory to reflect changes made during "
            "the current task, editing only what the work touched."
        ),
        "template_file": "maintain-skills.md",
    },
    {
        "name": "quartermaster_pin_file",
        "title": "Quartermaster Version-Pin File",
        "intent": (
            "The canonical `.quartermaster.toml` schema plus the read/pass/"
            "write workflow for remembering which major version of a kit a "
            "repo follows across breaking changes."
        ),
        "template_file": "quartermaster-toml.md",
    },
    {
        "name": "catalog_evaluation",
        "title": "Evaluate a Kit Catalog",
        "intent": (
            "Runbook for a kit author's agent to evaluate how well a kit "
            "catalog resolves — coverage, hit rate, false-exclusions, and "
            "cross-kit interference — over the local kit folder, for authoring "
            "new kits, reviewing existing ones, or checking a change's impact."
        ),
        "template_file": "catalog-evaluation.md",
    },
]


def _materialize(entry: dict[str, str]) -> dict[str, str]:
    """Return a public prompt dict with its markdown body loaded."""
    body = render_asset("prompts", entry["template_file"])
    return {
        "name": entry["name"],
        "title": entry["title"],
        "intent": entry["intent"],
        "prompt_template": _bake_image_channel(body),
    }


def list_canned_prompts() -> list[dict[str, str]]:
    """Return all canned prompt definitions."""
    return [_materialize(entry) for entry in _PROMPTS]


def get_canned_prompt(name: str) -> dict[str, str]:
    """
    Return a canned prompt by name.

    :raises KeyError: If *name* does not match a canned prompt.
    """
    for entry in _PROMPTS:
        if entry["name"] == name:
            return _materialize(entry)
    raise KeyError(name)
