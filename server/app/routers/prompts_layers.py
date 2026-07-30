"""
Layer-namespaced prompt CRUD endpoints.

Exposes each configured prompt layer as a virtual path segment so callers
can read and write a specific layer rather than the merged view. The
merged-view endpoints in ``prompts_admin`` remain the default. Mirrors
``app.routers.kits_layers`` but for the sectionless prompts catalog.

URL shape:
  GET    /api/prompts/layers                       → list layers
  GET    /api/prompts/layers/{layer_id}             → list prompts in layer
  POST   /api/prompts/layers/{layer_id}             → create prompt in layer
  GET    /api/prompts/layers/{layer_id}/{name}      → prompt detail in layer
  PUT    /api/prompts/layers/{layer_id}/{name}      → replace prompt in layer
  DELETE /api/prompts/layers/{layer_id}/{name}      → delete prompt from layer
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Response, status

from app import prompt_catalog as prompts_mod
from app.authz import require_editor
from app.catalog.router_base import new_api_router
from app.routers.prompts_admin import PromptCreate, PromptUpdate
from app.services import prompt_catalog_service as svc
from app.services.prompt_catalog_service import _layer_path, _layer_write_path

router = new_api_router(prefix="/api/prompts/layers", tags=["prompt-layers"])


@router.get("")
def list_layers() -> list[dict[str, Any]]:
    """Return all configured prompt layers (name, path, readonly)."""
    return svc.list_layers()


@router.get("/{layer_id}")
def list_prompts_in_layer(layer_id: str) -> list[dict[str, Any]]:
    """List prompts present in a specific layer (un-merged view)."""
    root = _layer_path(layer_id)
    prompts = []
    for name, path in prompts_mod._prompt_paths(root).items():
        title, description = prompts_mod._load_prompt_meta(path)
        prompts.append(
            {
                "name": name,
                "title": title,
                "description": description,
                "layer": layer_id,
            }
        )
    return prompts


@router.post(
    "/{layer_id}",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_prompt_in_layer(
    layer_id: str, payload: PromptCreate, response: Response
) -> dict[str, Any]:
    """Create a prompt in a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    detail = svc.put_prompt(
        name=payload.name,
        title=payload.title,
        description=payload.description,
        body=payload.body,
        root=root,
    )
    response.headers["Location"] = (
        f"/api/prompts/layers/{layer_id}/{payload.name}"
    )
    return svc.get_prompt_detail(detail.name, root=root)


@router.get("/{layer_id}/{name}")
def get_prompt_in_layer(layer_id: str, name: str) -> dict[str, Any]:
    """Return prompt detail from a specific layer (un-merged)."""
    root = _layer_path(layer_id)
    return svc.get_prompt_detail(name, root=root)


@router.put(
    "/{layer_id}/{name}",
    dependencies=[Depends(require_editor)],
)
def put_prompt_in_layer(
    layer_id: str, name: str, payload: PromptUpdate
) -> dict[str, Any]:
    """Create or replace a prompt in a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    detail = svc.put_prompt(
        name=name,
        title=payload.title,
        description=payload.description,
        body=payload.body,
        root=root,
    )
    return svc.get_prompt_detail(detail.name, root=root)


@router.delete(
    "/{layer_id}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_prompt_from_layer(layer_id: str, name: str) -> Response:
    """Delete a prompt from a specific layer (idempotent, 403 if readonly)."""
    root = _layer_write_path(layer_id)
    svc.delete_prompt(name, root=root)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
