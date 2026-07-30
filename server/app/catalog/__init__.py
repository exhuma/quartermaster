"""
Generic, content-agnostic "layered directory catalog" primitives.

This package factors out the layering, access-control, and merge machinery
that ``app.kits`` (and its storage/service/router layers) implement for
instruction kits, so a future second catalog type can reuse the same
mechanics instead of duplicating them. Nothing in this package knows about
kits specifically — kit-shaped behaviour lives in ``app.kits`` and friends,
implemented as thin wrappers around the generic pieces here.
"""

from __future__ import annotations
