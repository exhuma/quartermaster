"""
Shared Pydantic request models for the kit CRUD routers.

``kits_admin`` (merged catalog), ``kits_layers`` (per-layer), and
``private_kits`` (owner-scoped) all accept the same section/kit/version
request shapes over their respective URL spaces. This module is the single
definition each router imports from, instead of each defining its own
verbatim copy.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.services import kit_service as svc


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


def section_inputs(sections: list[SectionBody]) -> list[svc.SectionInput]:
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
