"""
Dev-only login router (module-dev-auth-bypass).

Mints HS256 dev tokens so the SPA (and scripts/E2E) can authenticate
without Keycloak. This router is imported and mounted **only** inside the
``dev_auth_enabled`` branch of the app factory, so ``/auth/dev/*`` is a
plain 404 in production rather than a route that merely rejects.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.config import get_settings
from app.dev_auth import mint_dev_token

router = APIRouter(prefix="/auth/dev", tags=["dev-auth"])


@router.get("/token")
def dev_token(username: str = "dev") -> dict[str, Any]:
    """
    Mint a dev bearer token for local development.

    :param username: Dev identity to embed in the token.
    :returns: ``{access_token, token_type}``.
    :raises HTTPException: ``503`` if the dev shared secret is unset.
    """
    settings = get_settings()
    if not settings.dev_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DEV_SHARED_SECRET is not configured.",
        )
    token = mint_dev_token(
        settings, sub=f"dev:{username}", username=username
    )
    return {"access_token": token, "token_type": "Bearer"}
