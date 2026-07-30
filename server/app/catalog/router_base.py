"""Shared ``APIRouter`` boilerplate for ``/api`` catalog routers.

Every ``/api`` router over a catalog (kit CRUD, kit layers, private kits,
and eventually a second catalog type) repeats the same
``default_response_class`` + vendor-``Accept`` dependency + 406 response
doc wiring. This module centralizes that construction so each router file
only supplies its own prefix/tags.
"""

from __future__ import annotations

from enum import Enum

from fastapi import APIRouter, Depends

from app.media_types import VendorJSONResponse, require_vendor_accept


def new_api_router(
    *, prefix: str, tags: list[str | Enum]
) -> APIRouter:
    """
    Build an ``/api`` router with the standard vendor-media-type wiring.

    :param prefix: URL prefix for every route on this router, e.g.
        ``"/api/kits/layers"``.
    :param tags: OpenAPI tags applied to this router's endpoints.
    :returns: A configured, empty ``APIRouter`` ready for route
        registration.
    """
    return APIRouter(
        prefix=prefix,
        tags=tags,
        default_response_class=VendorJSONResponse,
        dependencies=[Depends(require_vendor_accept)],
        responses={406: {"description": "Vendor media type not requested."}},
    )
