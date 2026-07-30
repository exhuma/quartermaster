"""
Layer-namespaced kit CRUD endpoints.

Exposes each configured kit layer as a virtual path segment so callers can
read and write a specific layer rather than the merged view.  The merged-view
endpoints in ``kits_admin`` remain the default.

URL shape:
  GET  /api/kits/layers                                         → list layers
  GET  /api/kits/layers/{layer_id}                              → list kits in layer
  GET  /api/kits/layers/{layer_id}/{name}                       → kit detail in layer
  POST /api/kits/layers/{layer_id}                              → create kit in layer
  DELETE /api/kits/layers/{layer_id}/{name}                     → delete kit from layer
  GET  /api/kits/layers/{layer_id}/{name}/applicability         → applicability in layer
  PUT  /api/kits/layers/{layer_id}/{name}/applicability         → replace applicability
  GET  /api/kits/layers/{layer_id}/{name}/versions              → versions in layer
  POST /api/kits/layers/{layer_id}/{name}/versions              → add version to layer
  DELETE /api/kits/layers/{layer_id}/{name}/versions/{version}  → delete version
  GET  /api/kits/layers/{layer_id}/{name}/versions/{v}/outline  → outline in layer
  GET  /api/kits/layers/{layer_id}/{name}/versions/{v}/sections/{id}   → get section
  PUT  /api/kits/layers/{layer_id}/{name}/versions/{v}/sections/{id}   → put section
  DELETE /api/kits/layers/{layer_id}/{name}/versions/{v}/sections/{id} → delete section
"""

from __future__ import annotations

from typing import Any

from fastapi import Depends, Response, status

from app import kits as kits_mod
from app.authz import require_editor
from app.catalog.router_base import new_api_router
from app.routers.kit_schemas import KitCreate, SectionUpsert, VersionCreate
from app.routers.kit_schemas import section_inputs as _inputs
from app.services import kit_service as svc
from app.services.kit_service import _layer_path, _layer_write_path

router = new_api_router(prefix="/api/kits/layers", tags=["kit-layers"])


# ---------------------------------------------------------------------------
# Layer list
# ---------------------------------------------------------------------------


@router.get("")
def list_layers() -> list[dict[str, Any]]:
    """Return all configured kit layers (name, path, readonly)."""
    return svc.list_layers()


# ---------------------------------------------------------------------------
# Kits within a layer
# ---------------------------------------------------------------------------


@router.get("/{layer_id}")
def list_kits_in_layer(layer_id: str) -> list[dict[str, Any]]:
    """List kits present in a specific layer (un-merged view)."""
    root = _layer_path(layer_id)
    all_versions = kits_mod._kit_version_paths(root)
    kits = []
    for name, versions in all_versions.items():
        latest = max(versions, key=kits_mod._version_key)
        index = kits_mod._load_kit_index(versions[latest], name)
        kits.append({
            "name": name,
            "description": index.summary,
            "versions": list(versions.keys()),
            "latest_version": latest,
            "layer": layer_id,
        })
    return kits


@router.post(
    "/{layer_id}",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_kit_in_layer(
    layer_id: str, payload: KitCreate, response: Response
) -> dict[str, Any]:
    """Create a kit in a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    detail = svc.create_kit(
        name=payload.name,
        applicability=payload.applicability,
        summary=payload.summary,
        sections=_inputs(payload.sections),
        changelog=payload.changelog,
        version=payload.version,
        root=root,
    )
    response.headers["Location"] = (
        f"/api/kits/layers/{layer_id}/{payload.name}"
    )
    return detail


@router.get("/{layer_id}/{name}")
def get_kit_in_layer(layer_id: str, name: str) -> dict[str, Any]:
    """Return kit detail from a specific layer (un-merged)."""
    root = _layer_path(layer_id)
    return svc.get_kit_detail(name, root=root)


@router.delete(
    "/{layer_id}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_kit_from_layer(layer_id: str, name: str) -> Response:
    """Delete a kit from a specific layer (idempotent, 403 if readonly)."""
    root = _layer_write_path(layer_id)
    svc.delete_kit(name, root=root)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Applicability manifest
# ---------------------------------------------------------------------------


@router.get("/{layer_id}/{name}/applicability")
def get_applicability_in_layer(
    layer_id: str, name: str
) -> dict[str, Any]:
    """Return a kit's applicability manifest from a specific layer."""
    root = _layer_path(layer_id)
    return svc.get_applicability(name, root=root)


@router.put(
    "/{layer_id}/{name}/applicability",
    dependencies=[Depends(require_editor)],
)
def replace_applicability_in_layer(
    layer_id: str, name: str, applicability: dict[str, Any]
) -> dict[str, Any]:
    """Replace a kit's applicability manifest in a specific layer."""
    root = _layer_write_path(layer_id)
    return svc.replace_applicability(name, applicability, root=root)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@router.get("/{layer_id}/{name}/versions")
def list_versions_in_layer(layer_id: str, name: str) -> list[str]:
    """List a kit's versions in a specific layer."""
    root = _layer_path(layer_id)
    return svc.list_versions(name, root=root)


@router.post(
    "/{layer_id}/{name}/versions",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_editor)],
)
def create_version_in_layer(
    layer_id: str,
    name: str,
    payload: VersionCreate,
    response: Response,
) -> list[str]:
    """Add a new version to a kit in a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    versions = svc.create_version(
        name,
        payload.version,
        summary=payload.summary,
        sections=_inputs(payload.sections),
        root=root,
    )
    response.headers["Location"] = (
        f"/api/kits/layers/{layer_id}/{name}/versions/{payload.version}"
    )
    return versions


@router.delete(
    "/{layer_id}/{name}/versions/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_version_from_layer(
    layer_id: str, name: str, version: str
) -> Response:
    """Delete a version from a kit in a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    svc.delete_version(name, version, root=root)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{layer_id}/{name}/versions/{version}/outline")
def get_outline_in_layer(
    layer_id: str, name: str, version: str
) -> dict[str, Any]:
    """Return the section outline for a kit version in a specific layer."""
    root = _layer_path(layer_id)
    return kits_mod.read_kit_outline(name, version, root=root)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@router.get(
    "/{layer_id}/{name}/versions/{version}/sections/{section_id}"
)
def get_section_in_layer(
    layer_id: str, name: str, version: str, section_id: str
) -> dict[str, Any]:
    """Return a section's metadata and body from a specific layer."""
    root = _layer_path(layer_id)
    return svc.get_section(name, version, section_id, root=root)


@router.put(
    "/{layer_id}/{name}/versions/{version}/sections/{section_id}",
    dependencies=[Depends(require_editor)],
)
def put_section_in_layer(
    layer_id: str,
    name: str,
    version: str,
    section_id: str,
    payload: SectionUpsert,
) -> dict[str, Any]:
    """Create or replace a section in a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    return svc.put_section(
        name,
        version,
        section_id,
        title=payload.title,
        gloss=payload.gloss,
        always_load=payload.always_load,
        body=payload.body,
        root=root,
    )


@router.delete(
    "/{layer_id}/{name}/versions/{version}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_editor)],
)
def delete_section_from_layer(
    layer_id: str, name: str, version: str, section_id: str
) -> Response:
    """Delete a section from a specific layer (403 if readonly)."""
    root = _layer_write_path(layer_id)
    svc.delete_section(name, version, section_id, root=root)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
