"""Current-user endpoint: identity + effective role.

The SPA needs to know whether to render editing controls. Rather than trust a
role claim the token may not carry, the server is the source of truth: it
reports the caller's stable ``sub``, a display ``label``, and their effective
role from the role store.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.authz import current_role
from app.media_types import VendorJSONResponse, require_vendor_accept

router = APIRouter(
    prefix="/api",
    tags=["me"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
    responses={406: {"description": "Vendor media type not requested."}},
)


@router.get("/me")
def get_me(request: Request) -> dict[str, str]:
    """Return the authenticated caller's subject, label, and effective role."""
    return {
        "sub": getattr(request.state, "auth_sub", "") or "",
        "label": getattr(request.state, "auth_label", "") or "",
        "role": current_role(request),
    }
