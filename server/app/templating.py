"""Load bundled markdown text assets and render them with ``str.format()``.

Text content that is more comfortably authored as prose — MCP prompt bodies,
the server-level instructions string, and similar blocks — lives as raw
markdown under ``app/assets/`` rather than as escaped inline Python string
literals. This module is the single seam for loading those files.

Assets are shipped inside the package (see ``[tool.setuptools.package-data]``
in ``pyproject.toml``) and read via :mod:`importlib.resources`, so they resolve
whether the app runs from a source checkout or an installed wheel.
"""

from __future__ import annotations

from importlib.resources import files


def load_asset(*parts: str) -> str:
    """Return the raw text of a bundled asset under ``app/assets/``.

    :param parts: Path segments below ``app/assets`` (e.g. ``"prompts",
        "greet.md"``).
    """
    return files("app").joinpath("assets", *parts).read_text(encoding="utf-8")


def render_asset(*parts: str, **variables: object) -> str:
    """Load a bundled asset and render it with ``str.format(**variables)``.

    When no *variables* are given the raw text is returned untouched, so static
    templates that contain literal ``{``/``}`` need no escaping. Templates that
    do interpolate use ``{name}`` placeholders and must double any literal
    braces (``{{``), per :meth:`str.format`.

    :param parts: Path segments below ``app/assets`` (the final one is the
        ``.md`` filename).
    :param variables: Substitutions applied via :meth:`str.format`.
    """
    raw = load_asset(*parts)
    return raw.format(**variables) if variables else raw
