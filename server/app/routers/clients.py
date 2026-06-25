"""
Client (User-Agent) registration API.

Lets a programmatic client register its ``User-Agent`` so it is allowed
through the :class:`~app.user_agent.UserAgentMiddleware` gate. Simple by
design: it identifies clients, it is not a strong access control. The
``POST`` route is exempt from the User-Agent gate (a client must be able
to register before it is known) but still requires a valid token like the
rest of ``/api``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.storage import client_registry

router = APIRouter(
    prefix="/api",
    tags=["clients"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
)


class ClientRegister(BaseModel):
    """Request body to register a client User-Agent."""

    user_agent: str = Field(min_length=1)
    label: str = ""


@router.post("/clients", status_code=status.HTTP_201_CREATED)
def register_client(payload: ClientRegister) -> dict[str, Any]:
    """Register (or update) a client User-Agent (idempotent)."""
    return client_registry.register(
        get_settings().client_registry_path,
        payload.user_agent,
        payload.label,
    )


@router.get("/clients")
def list_clients() -> list[dict[str, Any]]:
    """List registered client User-Agents."""
    return client_registry.load_clients(get_settings().client_registry_path)


@router.delete(
    "/clients/{client_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_client(client_id: str) -> Response:
    """Remove a registered client by id (idempotent)."""
    client_registry.unregister(
        get_settings().client_registry_path, client_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
