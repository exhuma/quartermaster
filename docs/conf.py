"""Sphinx configuration for the Quartermaster documentation site.

The site is built with ``sphinx-build -W`` (warnings are errors) and bundled
into the release Docker image, where it is served at ``/docs`` (see
``server/app/docs_site.py``). Authoring conventions follow the project's own
``module-docs-sphinx`` and ``module-documentation`` kits.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

_DOCS_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _DOCS_ROOT.parent

# autodoc imports the backend package. The server uses ``pythonpath = ["."]``
# (see server/pyproject.toml) which Sphinx does not inherit, so add the source
# root to sys.path explicitly. Two candidates cover both build contexts: a
# local checkout keeps ``app`` under ``server/``; the Docker docs stage copies
# it to the build root (``/build/app``).
for _src in (_REPO_ROOT / "server", _REPO_ROOT):
    if (_src / "app").is_dir():
        sys.path.insert(0, str(_src))

# -- Project information -----------------------------------------------------

project = "Quartermaster"
author = "Quartermaster contributors"
copyright = "Quartermaster contributors"  # noqa: A001 - Sphinx-required name


def _resolve_release() -> str:
    """
    Resolve the documented version without hard-coding it.

    The documented version tracks the *released* (CalVer) version, resolved in
    order:

    1. the ``APP_VERSION`` build arg (``git describe --tags``) injected at
       image-build time (``server/Dockerfile`` docs stage);
    2. ``git describe --tags`` on the local checkout, so a local build shows the
       current release tag (e.g. ``2026.7.14-alpha.1``) rather than the
       decoupled ``server/pyproject.toml`` placeholder;
    3. the ``server/pyproject.toml`` version, a last resort for a build with no
       git metadata (e.g. an exported source tarball).

    :returns: The version string to document.
    """
    override = os.environ.get("APP_VERSION", "").strip()
    if override:
        return override.lstrip("v")
    try:
        described = subprocess.run(
            ["git", "describe", "--tags"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        if described:
            return described.lstrip("v")
    except (OSError, subprocess.SubprocessError):
        pass
    pyproject = _REPO_ROOT / "server" / "pyproject.toml"
    try:
        with pyproject.open("rb") as handle:
            return tomllib.load(handle)["project"]["version"]
    except (FileNotFoundError, KeyError):
        return "0.0.0"


release = _resolve_release()
version = ".".join(release.split(".")[:2])

# -- General configuration ---------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosectionlabel",
    "sphinx.ext.intersphinx",
    "sphinx_autodoc_typehints",
    "myst_parser",
    "sphinx_copybutton",
    "sphinxcontrib.mermaid",
]

# Prefix cross-document section labels with the document name so identically
# titled sections across pages do not collide.
autosectionlabel_prefix_document = True
# Only label h1/h2. The included CHANGELOG repeats h3 headings ("### Added",
# "### Changed") within one document, which would otherwise produce duplicate
# labels; nothing cross-references those anchors.
autosectionlabel_maxdepth = 2

# Silence two third-party typehint-resolution warnings emitted while
# autodoc-ing the pydantic-settings ``Settings`` model — pydantic's internal
# ``JsonValue`` forward reference and a guarded import in its validators. They
# are noise from the dependency, not our docs.
suppress_warnings = [
    "sphinx_autodoc_typehints.forward_reference",
    "sphinx_autodoc_typehints.guarded_import",
]

# MyST is the authoring format for this site (the source docs are Markdown).
myst_enable_extensions = ["colon_fence", "deflist"]
# Generate anchors for h1/h2 so in-page and cross-page links to headings work.
myst_heading_anchors = 3
# Let plain ```mermaid fenced blocks render as the sphinxcontrib.mermaid
# directive, so diagrams stay diffable next to the prose (module-diagrams).
myst_fence_as_directive = ["mermaid"]

# -- sphinx-copybutton -------------------------------------------------------
# A copy button on every code block. Strip shell/REPL prompts and any command
# output so a click copies the runnable command, not the "$" or the result.
copybutton_prompt_text = r"\$ |# |>>> |\.\.\. "
copybutton_prompt_is_regexp = True
# Don't attach the button to Mermaid source or to line-number gutters.
copybutton_exclude = ".linenos, .gp"

# The ``superpowers/`` tree holds an unrelated design spec that is not part of
# the published site; keep it out so it does not trip the "not in any toctree"
# check under ``-W``.
exclude_patterns = ["_build", "superpowers", "Thumbs.db", ".DS_Store"]

templates_path = ["_templates"]

# -- autodoc -----------------------------------------------------------------

autodoc_default_options = {
    "members": True,
    "undoc-members": True,
    "show-inheritance": True,
}
autodoc_typehints = "description"

# -- intersphinx -------------------------------------------------------------
# Add mappings only for libraries actually cross-referenced in the docs.

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "fastapi": ("https://fastapi.tiangolo.com/", None),
    "pydantic": ("https://docs.pydantic.dev/latest/", None),
}

# -- HTML output -------------------------------------------------------------

html_theme = "furo"
html_static_path = ["_static"]
html_title = f"Quartermaster {release}"


# -- release-channel baking --------------------------------------------------
# Docker examples in the Markdown source reference the default `alpha` channel
# (readable and correct today). Since the docs are bundled into each release
# image, rewrite that tag to the channel THIS build advances so the served
# docs point at their own image. The channel is injected via the QM_RELEASE_
# CHANNEL env var (docs Docker stage, from scripts/derive_channels.sh
# --primary); it defaults to `alpha` for local builds. Done on the raw source
# (source-read) so it also applies inside fenced code blocks, which MyST
# substitutions do not reach.
_DEFAULT_CHANNEL = "alpha"
_CHANNEL = os.environ.get("QM_RELEASE_CHANNEL", "").strip() or _DEFAULT_CHANNEL
_IMAGE_BASE = "ghcr.io/exhuma/quartermaster"


def _bake_channel(_app: object, _docname: str, source: list[str]) -> None:
    if _CHANNEL == _DEFAULT_CHANNEL:
        return
    source[0] = source[0].replace(
        f"{_IMAGE_BASE}:{_DEFAULT_CHANNEL}", f"{_IMAGE_BASE}:{_CHANNEL}"
    )


def setup(app: object) -> dict[str, object]:
    app.connect("source-read", _bake_channel)  # type: ignore[attr-defined]
    return {"parallel_read_safe": True, "parallel_write_safe": True}
