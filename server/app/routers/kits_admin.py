"""
Kit CRUD admin API (REST over the kit catalog).

Thin routing layer per the module-fastapi 3-layer rule: parse and
validate the request, delegate to ``app.services.kit_service``, and let
domain exceptions propagate to the handlers registered in
``app.main.create_app``. No business logic and no filesystem access here.

URL design follows the module-api-design kit: nouns only (no verbs in
paths), no version segment in the URL — API versioning, when needed, is by
media type. PUT/DELETE are idempotent.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel

from app import kits as kits_mod
from app.media_types import VendorJSONResponse, require_vendor_accept
from app.services import kit_service as svc

router = APIRouter(
    prefix="/api",
    tags=["kits"],
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
    """Request body to create a kit with its initial version."""

    name: str
    applicability: dict[str, Any]
    summary: str
    sections: list[SectionBody]
    changelog: str | None = None
    version: str = "v1"


class VersionCreate(BaseModel):
    """Request body to add a new major version to a kit."""

    version: str
    summary: str
    sections: list[SectionBody]


class SectionUpsert(BaseModel):
    """Request body to create or replace a single section."""

    title: str
    gloss: str = ""
    always_load: bool = False
    body: str


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


# ---------------------------------------------------------------------------
# Kits
# ---------------------------------------------------------------------------


@router.get("/traits")
def list_traits() -> dict[str, Any]:
    """Return the trait vocabularies observed across all kit manifests."""
    return kits_mod.list_available_traits_v2()


@router.get("/kits")
def list_kits() -> list[dict[str, Any]]:
    """List all kits with compact metadata."""
    return svc.list_kits()


@router.post("/kits", status_code=status.HTTP_201_CREATED)
def create_kit(payload: KitCreate) -> dict[str, Any]:
    """Create a kit with its initial version."""
    return svc.create_kit(
        name=payload.name,
        applicability=payload.applicability,
        summary=payload.summary,
        sections=_inputs(payload.sections),
        changelog=payload.changelog,
        version=payload.version,
    )


@router.get("/kits/{name}")
def get_kit(name: str) -> dict[str, Any]:
    """Return detail for a single kit."""
    return svc.get_kit_detail(name)


@router.delete("/kits/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_kit(name: str) -> Response:
    """Delete a kit and all its versions (idempotent)."""
    svc.delete_kit(name)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Applicability manifest
# ---------------------------------------------------------------------------


@router.get("/kits/{name}/applicability")
def get_applicability(name: str) -> dict[str, Any]:
    """Return a kit's stored ``applicability.json``."""
    return svc.get_applicability(name)


@router.put("/kits/{name}/applicability")
def replace_applicability(
    name: str, applicability: dict[str, Any]
) -> dict[str, Any]:
    """Replace a kit's applicability manifest (idempotent)."""
    return svc.replace_applicability(name, applicability)


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


@router.get("/kits/{name}/versions")
def list_versions(name: str) -> list[str]:
    """List a kit's major versions, oldest first."""
    return svc.list_versions(name)


@router.post(
    "/kits/{name}/versions", status_code=status.HTTP_201_CREATED
)
def create_version(name: str, payload: VersionCreate) -> list[str]:
    """Add a new major version to a kit."""
    return svc.create_version(
        name,
        payload.version,
        summary=payload.summary,
        sections=_inputs(payload.sections),
    )


@router.delete(
    "/kits/{name}/versions/{version}",
    status_code=status.HTTP_200_OK,
)
def delete_version(name: str, version: str) -> list[str]:
    """Delete one major version of a kit (idempotent)."""
    return svc.delete_version(name, version)


@router.get("/kits/{name}/versions/{version}/outline")
def get_outline(name: str, version: str) -> dict[str, Any]:
    """Return the cheap section map for a kit version."""
    return kits_mod.read_kit_outline(name, version)


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


@router.get("/kits/{name}/versions/{version}/sections/{section_id}")
def get_section(
    name: str, version: str, section_id: str
) -> dict[str, Any]:
    """Return one section's metadata and body."""
    return svc.get_section(name, version, section_id)


@router.put("/kits/{name}/versions/{version}/sections/{section_id}")
def put_section(
    name: str,
    version: str,
    section_id: str,
    payload: SectionUpsert,
) -> dict[str, Any]:
    """Create or replace a section (idempotent)."""
    return svc.put_section(
        name,
        version,
        section_id,
        title=payload.title,
        gloss=payload.gloss,
        always_load=payload.always_load,
        body=payload.body,
    )


@router.delete(
    "/kits/{name}/versions/{version}/sections/{section_id}",
    status_code=status.HTTP_200_OK,
)
def delete_section(
    name: str, version: str, section_id: str
) -> list[str]:
    """Delete a section from a version (idempotent)."""
    return svc.delete_section(name, version, section_id)


# ---------------------------------------------------------------------------
# Changelog / comparison
# ---------------------------------------------------------------------------


@router.get("/kits/{name}/changelog")
def get_changelog(name: str) -> dict[str, str]:
    """Return the raw ``CHANGELOG.md`` text for a kit."""
    return {"changelog": svc.get_changelog(name)}


@router.get("/kits/{name}/compare")
def compare_versions(
    name: str,
    from_version: str = Query(alias="from"),
    to_version: str = Query(alias="to"),
) -> dict[str, Any]:
    """Summarise changes between two versions from the changelog."""
    return kits_mod.compare_kit_versions(name, from_version, to_version)
