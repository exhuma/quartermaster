"""
Per-user WebDAV app-token API.

An OIDC-authenticated user mints a long-lived app token here, then uses it
as the HTTP Basic password when mounting the kit catalog over WebDAV (OS
mount dialogs cannot run a browser OIDC flow). The plaintext token is
returned **once** at mint time and never stored. Tokens are scoped to the
caller (identified from the validated JWT via ``request.state``).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.config import get_settings
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.rate_limit import enforce_limit_or_429
from app.storage import app_tokens

router = APIRouter(
    prefix="/api",
    tags=["app-tokens"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
)


class AppTokenCreate(BaseModel):
    """Request body to mint an app token."""

    label: str = ""


def _subject(request: Request) -> str:
    """Return the authenticated caller, or 401 if somehow absent."""
    subject = getattr(request.state, "auth_subject", "")
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authenticated user.",
        )
    return subject


@router.post("/app-tokens", status_code=status.HTTP_201_CREATED)
def mint_app_token(
    payload: AppTokenCreate, request: Request, response: Response
) -> dict[str, Any]:
    """
    Mint a WebDAV app token for the current user.

    The ``token`` field is the plaintext credential — shown once, never
    stored. Use it as the Basic password when mounting ``/dav``.
    """
    subject = _subject(request)
    enforce_limit_or_429(
        key=f"mint-app-token:{subject}",
        limit=10,
        window_seconds=60,
        scope="app-token minting",
    )
    record, token = app_tokens.mint(
        get_settings().app_tokens_path, subject, payload.label
    )
    response.headers["Location"] = f"/api/app-tokens/{record['id']}"
    return {**record, "token": token}


@router.get("/app-tokens")
def list_app_tokens(request: Request) -> list[dict[str, Any]]:
    """List the current user's app tokens (no secrets)."""
    return app_tokens.list_for(
        get_settings().app_tokens_path, _subject(request)
    )


@router.delete(
    "/app-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_app_token(token_id: str, request: Request) -> Response:
    """Revoke one of the current user's app tokens (idempotent)."""
    app_tokens.revoke(
        get_settings().app_tokens_path, token_id, _subject(request)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
