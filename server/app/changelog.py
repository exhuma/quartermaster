"""Serve the project's behaviour-focused changelog to the public web UI.

The changelog is authored once in the repo-root ``changelog.in`` and rendered
to JSON by clproc (``task changelog``) into the bundled asset
``app/assets/text/changelog.json``. This module is the thin runtime seam that
reads that generated asset; there is no parsing or business logic here — clproc
owns the format. The JSON is served verbatim over a public, unauthenticated
endpoint (see :func:`app.main.changelog_json`), so the changelog is legible
before sign-in.

The rendered shape is a JSON array of releases, newest first::

    [ { "logs": [ { "subject", "type", "detail", "is_highlight",
                     "is_internal", "issue_ids", "issue_urls", ... } ],
        "meta": { "version", "date", "notes" } }, ... ]

``meta.date`` is ``null`` for the not-yet-tagged (unreleased) group.
"""

from __future__ import annotations

import logging

from app.templating import load_asset

logger = logging.getLogger(__name__)

# Empty changelog: a valid, well-typed payload the SPA renders as "no entries"
# rather than erroring. Used only if the generated asset is absent (e.g. a
# source checkout where `task changelog` has not been run yet).
_EMPTY_CHANGELOG = "[]"


def load_changelog_json() -> str:
    """Return the rendered changelog JSON as a raw string.

    The asset is served verbatim (already valid JSON), so no parse/re-encode
    round-trip is needed. A missing asset degrades to an empty array rather
    than failing the public page.

    :returns: The contents of ``app/assets/text/changelog.json``, or ``"[]"``
        when that asset has not been generated.
    """
    try:
        return load_asset("text", "changelog.json")
    except FileNotFoundError:
        logger.warning(
            "changelog.json asset is missing; serving an empty changelog. "
            "Run `task changelog` to render it from changelog.in."
        )
        return _EMPTY_CHANGELOG
