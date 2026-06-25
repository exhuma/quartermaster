"""
Integration metadata API for the web UI.

Read-only endpoint that feeds the "how to integrate the MCP into a coding
agent" page: the MCP endpoint URL, the Keycloak realm/endpoints the SPA and
agents authenticate against, and which auth modes are enabled. All values
derive from :class:`~app.config.Settings`; nothing here touches the catalog.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.media_types import (
    VENDOR_MEDIA_TYPE,
    VendorJSONResponse,
    require_vendor_accept,
)

router = APIRouter(
    prefix="/api",
    tags=["integration"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
    responses={406: {"description": "Vendor media type not requested."}},
)


@router.get("/integration")
def integration() -> dict[str, Any]:
    """
    Return the data the web UI's integration page needs.

    :returns: Server origin, MCP URL, Keycloak/OAuth discovery details,
        the SPA public client id, and which auth modes are enabled.
    """
    settings = get_settings()
    return {
        "server_origin": settings.server_origin,
        "mcp_url": f"{settings.server_origin}/kits/mcp",
        "keycloak_issuer": settings.keycloak_issuer,
        "keycloak_realm": settings.keycloak_realm,
        "webui_client_id": settings.webui_keycloak_client_id,
        "oauth_scopes": settings.oauth_scopes,
        "oauth_metadata_url": settings.oauth_metadata_url,
        "authorization_endpoint": settings.authorization_endpoint,
        "token_endpoint": settings.token_endpoint,
        "copilot_auth_enabled": settings.copilot_auth_enabled,
        "api_media_type": VENDOR_MEDIA_TYPE,
        "client_registration_url": f"{settings.server_origin}/api/clients",
    }
