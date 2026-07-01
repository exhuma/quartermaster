"""Role administration API (editor-only).

Editors are the system's admins: they grant and revoke the ``editor`` role
from other users. Roles key on the stable IdP subject (``sub``); a
human-readable label is stored alongside for display. Bootstrap editors
(``QM_INITIAL_EDITORS``) are shown as read-only rows and cannot be revoked.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel

from app.authz import require_editor
from app.config import get_settings
from app.kits import KitValidationError
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.storage import role_store

router = APIRouter(
    prefix="/api",
    tags=["roles"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept), Depends(require_editor)],
    responses={
        403: {"description": "Editor role required."},
        406: {"description": "Vendor media type not requested."},
    },
)


class RoleAssignment(BaseModel):
    """Request body to assign a role to a subject."""

    role: str
    label: str = ""


@router.get("/roles")
def list_roles() -> list[dict[str, Any]]:
    """List every known subject with its effective role."""
    settings = get_settings()
    return role_store.list_all(
        settings.role_store_path, initial_editors=settings.initial_editors
    )


@router.put("/roles/{sub}")
def set_role(sub: str, payload: RoleAssignment) -> dict[str, Any]:
    """Assign a role to *sub* (idempotent).

    :raises KitValidationError: On an unknown role (mapped to 422).
    """
    settings = get_settings()
    try:
        return role_store.set_role(
            settings.role_store_path, sub, payload.role, payload.label
        )
    except ValueError as exc:
        raise KitValidationError(str(exc)) from exc


@router.delete("/roles/{sub}", status_code=status.HTTP_204_NO_CONTENT)
def remove_role(sub: str) -> Response:
    """Revert *sub* to the default role (idempotent).

    :raises KitValidationError: When *sub* is a bootstrap editor (mapped to
        422) — env-seeded editors cannot be revoked.
    """
    settings = get_settings()
    try:
        role_store.remove(
            settings.role_store_path,
            sub,
            initial_editors=settings.initial_editors,
        )
    except ValueError as exc:
        raise KitValidationError(str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
