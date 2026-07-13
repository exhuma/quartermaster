"""
Catalog-evaluation API for kit authors.

Runs a corpus of tasks through the in-process resolver and scores the outcome,
so authors can judge their catalog's resolution quality, coverage, and hit rate
(most usefully: which kits get silently excluded by over-inferred traits). The
run is asynchronous — ``POST`` starts a job, ``GET`` polls it for the report.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field

from app.media_types import VendorJSONResponse, require_vendor_accept
from app.services import eval_service as svc

router = APIRouter(
    prefix="/api",
    tags=["eval"],
    default_response_class=VendorJSONResponse,
    dependencies=[Depends(require_vendor_accept)],
    responses={406: {"description": "Vendor media type not requested."}},
)


class ResolutionEvalRequest(BaseModel):
    """Parameters for a resolution-eval run (all optional)."""

    cases: Literal["catalog", "authored", "all"] = "all"
    limit: int = Field(
        default=0, ge=0, description="cap number of cases (0 = all)"
    )


@router.post("/eval/resolution", status_code=status.HTTP_202_ACCEPTED)
def start_resolution_eval(
    payload: ResolutionEvalRequest | None = None,
) -> dict[str, Any]:
    """
    Start a resolution-eval run in the background.

    :returns: The job envelope (``job_id`` + ``status``); poll the GET endpoint
        with the id to retrieve the report once ``status`` is ``completed``.
    """
    params = payload or ResolutionEvalRequest()
    job = svc.start_resolution_eval(cases=params.cases, limit=params.limit)
    return job.to_public()


@router.get("/eval/resolution/{job_id}")
def get_resolution_eval(job_id: str) -> dict[str, Any]:
    """
    Poll a resolution-eval run.

    :returns: The job envelope; carries ``report`` when ``completed`` or
        ``error`` when ``failed``.
    :raises EvalJobNotFoundError: if *job_id* is unknown (mapped to 404).
    """
    return svc.get_resolution_eval(job_id).to_public()
