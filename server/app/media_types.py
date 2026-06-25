"""
Vendor media type and strict ``Accept`` negotiation for the REST API.

Per the module-api-design kit, every API request and response body uses a
vendor media type — never bare ``application/json``. Clients must declare
the vendor type in ``Accept``; a request for ``application/json`` or
``*/*`` is refused with **406 Not Acceptable** and a pointer to the docs,
so the contract is explicit rather than implicit. Responses always carry
the vendor ``Content-Type`` (symmetric: clients get exactly what they
asked for).
"""

from __future__ import annotations

from fastapi import Header, HTTPException, status
from fastapi.responses import JSONResponse

# Base type (used for matching) and the full versioned type (sent on
# responses). ``v`` is the major API version; bump it for breaking
# response-shape changes instead of versioning the URL.
VENDOR_BASE_TYPE = "application/vnd.instructions+json"
VENDOR_MEDIA_TYPE = f"{VENDOR_BASE_TYPE}; v=1"


class VendorJSONResponse(JSONResponse):
    """A ``JSONResponse`` whose ``Content-Type`` is the vendor media type."""

    media_type = VENDOR_MEDIA_TYPE


def _accept_ranges(accept: str) -> list[str]:
    """
    Return the lowercased base media types from an ``Accept`` header.

    Media-type parameters (``; q=…``, ``; v=…``) are stripped — only the
    ``type/subtype`` token of each comma-separated range is returned.

    :param accept: Raw ``Accept`` header value.
    :returns: List of base media-type tokens.
    """
    return [
        part.split(";", 1)[0].strip().lower()
        for part in accept.split(",")
        if part.strip()
    ]


def require_vendor_accept(accept: str = Header(default="")) -> None:
    """
    FastAPI dependency enforcing the vendor ``Accept`` type.

    :param accept: The request's ``Accept`` header.
    :raises HTTPException: ``406`` if the vendor type is not requested.
    """
    if any(r.startswith(VENDOR_BASE_TYPE) for r in _accept_ranges(accept)):
        return
    raise HTTPException(
        status_code=status.HTTP_406_NOT_ACCEPTABLE,
        detail=(
            f"This API serves only {VENDOR_MEDIA_TYPE!r}. Send an "
            f"'Accept: {VENDOR_MEDIA_TYPE}' header. 'application/json' and "
            f"'*/*' are not served. See /docs for the full contract."
        ),
    )
