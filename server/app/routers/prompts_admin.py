"""
Prompt CRUD admin API (REST over the shared prompts catalog, merged view).

Thin routing layer per the module-fastapi 3-layer rule: parse and validate
the request, delegate to ``app.services.prompt_catalog_service``, and let
domain exceptions propagate to the handlers registered in
``app.main.create_app``. No business logic and no filesystem access here.

Mirrors ``app.routers.kits_admin`` but for the separate, unversioned,
sectionless prompts catalog: nouns-only URLs, no version segment,
idempotent PUT/DELETE.
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Response, status
from pydantic import BaseModel

from app.authz import require_editor
from app.catalog.router_base import new_api_router
from app.services import prompt_catalog_service as svc

router = new_api_router(prefix="/api/prompts", tags=["prompts"])


class PromptCreate(BaseModel):
    """Request body to create a prompt."""

    name: str
    title: str = ""
    description: str = ""
    body: str


class PromptUpdate(BaseModel):
    """Request body to create or replace a prompt (name comes from the URL)."""

    title: str = ""
    description: str = ""
    body: str


@router.get("")
def list_prompts() -> list[dict[str, Any]]:
    """List all catalog prompts with compact metadata."""
    return svc.list_prompts()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_prompt(payload: PromptCreate, response: Response) -> dict[str, Any]:
    """Create a prompt in the shared catalog's default writable layer."""
    detail = svc.put_prompt(
        name=payload.name,
        title=payload.title,
        description=payload.description,
        body=payload.body,
    )
    response.headers["Location"] = f"/api/prompts/{payload.name}"
    return svc.get_prompt_detail(detail.name)


@router.get("/{name}")
def get_prompt(name: str) -> dict[str, Any]:
    """Return detail for a single prompt (merged view)."""
    return svc.get_prompt_detail(name)


@router.put(
    "/{name}",
    dependencies=[Depends(require_editor)],
)
def put_prompt(name: str, payload: PromptUpdate) -> dict[str, Any]:
    """Create or replace a prompt in the shared catalog (idempotent)."""
    detail = svc.put_prompt(
        name=name,
        title=payload.title,
        description=payload.description,
        body=payload.body,
    )
    return svc.get_prompt_detail(detail.name)


@router.delete(
    "/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_prompt(name: str) -> Response:
    """Delete a prompt from the shared catalog (idempotent, 204 no body)."""
    svc.delete_prompt(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
