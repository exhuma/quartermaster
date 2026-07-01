"""Private-kit CRUD API (owner-scoped).

A private kit is a standalone kit visible only to its owner. These routes are
gated by **ownership**, not the editor role: any authenticated user may manage
their own private kits (consumers included). Every operation is confined to the
caller's private root (``private_root_for(sub)``) by passing ``root=`` to the
shared :mod:`app.services.kit_service` functions — the same validate-before-
commit logic as the public catalog, just rooted at the owner's subtree.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from app import kits as kits_mod
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.private_kits import private_root_for
from app.services import kit_service as svc

router = APIRouter(
    prefix="/api/private-kits",
    tags=["private-kits"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
    responses={406: {"description": "Vendor media type not requested."}},
)


class SectionBody(BaseModel):
    """A section with its file basename, metadata, and body."""

    file: str
    title: str
    gloss: str = ""
    always_load: bool = False
    body: str


class KitCreate(BaseModel):
    """Request body to create a private kit with its initial version."""

    name: str
    applicability: dict[str, Any]
    summary: str
    sections: list[SectionBody]
    changelog: str | None = None
    version: str = "v1"


class SectionUpsert(BaseModel):
    """Request body to create or replace a single section."""

    title: str
    gloss: str = ""
    always_load: bool = False
    body: str


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
    """Return the caller's owner-scoped private-kit root."""
    return private_root_for(_subject(request))


def _inputs(sections: list[SectionBody]) -> list[svc.SectionInput]:
    """Convert request section models to service inputs."""
    return [
        svc.SectionInput(
            file=s.file,
            title=s.title,
            gloss=s.gloss,
            always_load=s.always_load,
            body=s.body,
        )
        for s in sections
    ]


@router.get("")
def list_private_kits(request: Request) -> list[dict[str, Any]]:
    """List the caller's own private kits (never anyone else's)."""
    kits = kits_mod.list_private_kits(_subject(request))
    return [
        {
            "name": k.name,
            "description": k.description,
            "versions": k.versions,
            "latest_version": k.latest_version,
        }
        for k in kits
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_private_kit(
    payload: KitCreate, request: Request, response: Response
) -> dict[str, Any]:
    """Create a private kit owned by the caller."""
    detail = svc.create_kit(
        name=payload.name,
        applicability=payload.applicability,
        summary=payload.summary,
        sections=_inputs(payload.sections),
        changelog=payload.changelog,
        version=payload.version,
        root=_root(request),
    )
    response.headers["Location"] = f"/api/private-kits/{payload.name}"
    return detail


@router.get("/{name}")
def get_private_kit(name: str, request: Request) -> dict[str, Any]:
    """Return detail for one of the caller's private kits (404 otherwise)."""
    return svc.get_kit_detail(name, root=_root(request))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_private_kit(name: str, request: Request) -> Response:
    """Delete one of the caller's private kits (idempotent)."""
    svc.delete_kit(name, root=_root(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{name}/versions/{version}/outline")
def get_private_outline(
    name: str, version: str, request: Request
) -> dict[str, Any]:
    """Return the section outline for a private kit version."""
    return kits_mod.read_kit_outline(name, version, root=_root(request))


@router.put("/{name}/versions/{version}/sections/{section_id}")
def put_private_section(
    name: str,
    version: str,
    section_id: str,
    payload: SectionUpsert,
    request: Request,
) -> dict[str, Any]:
    """Create or replace a section in one of the caller's private kits."""
    return svc.put_section(
        name,
        version,
        section_id,
        title=payload.title,
        gloss=payload.gloss,
        always_load=payload.always_load,
        body=payload.body,
        root=_root(request),
    )


@router.delete(
    "/{name}/versions/{version}/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_private_section(
    name: str, version: str, section_id: str, request: Request
) -> Response:
    """Delete a section from one of the caller's private kits (idempotent)."""
    svc.delete_section(name, version, section_id, root=_root(request))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
