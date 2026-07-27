"""
Free-text search API over the kit catalog (metadata + instruction content).

Read-only, thin routing layer per the module-fastapi 3-layer rule: parse
the query params and delegate to :func:`app.kits.search_catalog`, which
owns all scoring/matching logic. This is the read-side counterpart to
``resolve_kits``/``select_kits`` — those match a task onto the closed
trait vocabulary, this matches a literal phrase against kit metadata and
section content. No ``kit_service`` involvement: there is no mutation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.kits import search_catalog
from app.media_types import VendorJSONResponse, require_vendor_accept

router = APIRouter(
    prefix="/api",
    tags=["search"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
    responses={406: {"description": "Vendor media type not requested."}},
)


@router.get("/search")
def search(
    q: str = Query("", description="Free-text search phrase."),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Search kit names, applicability metadata, and section content."""
    return search_catalog(q, limit=limit)
