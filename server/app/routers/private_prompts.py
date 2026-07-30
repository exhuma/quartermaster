"""Private-prompt CRUD API (owner-scoped).

A private prompt is a Markdown file visible only to its owner. These routes
are gated by **ownership**, not the editor role: any authenticated user may
manage their own private prompts (consumers included). Every operation is
confined to the caller's private root (``private_root_for(sub)``) by passing
``root=`` to the shared :mod:`app.services.prompt_catalog_service` functions
— the same validate-before-commit logic as the shared catalog, just rooted
at the owner's subtree. Mirrors ``app.routers.private_kits``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request, Response, status

from app.catalog.router_base import new_api_router
from app.private_prompts import private_root_for
from app.prompt_catalog import list_private_prompts
from app.routers.prompts_admin import PromptCreate, PromptUpdate
from app.services import prompt_catalog_service as svc

router = new_api_router(prefix="/api/private-prompts", tags=["private-prompts"])


def _subject(request: Request) -> str:
    """Return the authenticated caller's stable subject, or 401."""
    sub = getattr(request.state, "auth_sub", "") or ""
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No authenticated user.",
        )
    return sub


def _root(request: Request):
    """Return the caller's owner-scoped private-prompt root."""
    return private_root_for(_subject(request))


@router.get("")
def list_own_private_prompts(request: Request) -> list[dict[str, Any]]:
    """List the caller's own private prompts (never anyone else's)."""
    prompts = list_private_prompts(_subject(request))
    return [
        {
            "name": p.name,
            "title": p.title,
            "description": p.description,
            "broken": p.broken,
            "error": p.error,
        }
        for p in prompts
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_private_prompt(
    payload: PromptCreate, request: Request, response: Response
) -> dict[str, Any]:
    """Create a private prompt owned by the caller."""
    root = _root(request)
    detail = svc.put_prompt(
        name=payload.name,
        title=payload.title,
        description=payload.description,
        body=payload.body,
        root=root,
    )
    response.headers["Location"] = f"/api/private-prompts/{payload.name}"
    return svc.get_prompt_detail(detail.name, root=root)


@router.get("/{name}")
def get_private_prompt(name: str, request: Request) -> dict[str, Any]:
    """Return detail for one of the caller's private prompts (404 otherwise)."""
    return svc.get_prompt_detail(name, root=_root(request))


@router.put("/{name}")
def put_private_prompt(
    name: str, payload: PromptUpdate, request: Request
) -> dict[str, Any]:
    """Create or replace one of the caller's private prompts (idempotent)."""
    root = _root(request)
    detail = svc.put_prompt(
        name=name,
        title=payload.title,
        description=payload.description,
        body=payload.body,
        root=root,
    )
    return svc.get_prompt_detail(detail.name, root=root)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_private_prompt(name: str, request: Request) -> Response:
    """Delete one of the caller's private prompts (idempotent)."""
    svc.delete_prompt(name, root=_root(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
