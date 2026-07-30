"""
Generic exception vocabulary for layered directory catalogs.

These are thin ``Exception`` subclasses shared by every catalog type. A
concrete catalog (e.g. kits, in ``app.kits``) defines its own exception
classes that subclass these directly, keeping their own ``__init__``/message
behaviour unchanged so every existing ``except``/``pytest.raises``/
``isinstance`` call site keeps working across the rename.
"""

from __future__ import annotations


class CatalogNotFoundError(Exception):
    """Raised when a requested catalog entry (or a part of one) is missing."""


class CatalogVersionNotFoundError(Exception):
    """Raised when a requested version of a catalog entry does not exist."""


class CatalogConflictError(Exception):
    """Raised when a write would collide with existing catalog content."""


class CatalogValidationError(Exception):
    """Raised when a proposed write would produce invalid catalog content."""


class CatalogLayerNotFoundError(Exception):
    """Raised when a requested layer identifier is not configured."""


class CatalogLayerReadonlyError(Exception):
    """Raised when a write is attempted on a read-only layer."""


class CatalogAccessError(Exception):
    """Raised when a caller references catalog content they may not access."""
