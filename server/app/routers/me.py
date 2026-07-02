"""Current-user endpoint: identity + effective role.

The SPA needs to know whether to render editing controls. Rather than trust a
role claim the token may not carry, the server is the source of truth: it
reports the caller's stable ``sub``, a display ``label``, and their effective
role from the role store.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.authz import current_role
from app.config import get_settings
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.storage import user_memory

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


def _require_subject(request: Request) -> str:
    """Return the authenticated caller, or 401 if somehow absent."""
    subject = getattr(request.state, "auth_sub", "") or ""
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authenticated user.",
        )
    return subject


@router.get("/me/memory")
def get_my_memory(request: Request) -> dict[str, Any]:
    """Return the caller's current derived memory profile.

    A small, capped summary of what the caller's own ``resolve_kits``
    history tends to touch, used only as a bounded ranking nudge — never a
    filter. Returns an empty profile (``updated`` null) when none has been
    derived yet.
    """
    subject = _require_subject(request)
    profile = user_memory.load_profile(
        get_settings().user_memory_store_path, subject
    )
    return profile or user_memory.empty_profile()


@router.delete("/me/memory", status_code=status.HTTP_204_NO_CONTENT)
def reset_my_memory(request: Request) -> Response:
    """Clear the caller's derived memory profile. Idempotent."""
    subject = _require_subject(request)
    user_memory.clear_profile(get_settings().user_memory_store_path, subject)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
