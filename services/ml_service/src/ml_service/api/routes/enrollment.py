"""Enrollment API (req §5.1, FR-E1/FR-E2) — the synchronous HTTP pipeline.

Student-id-triggered (decisions/0009): the backend sends ``school_id`` +
``student_id`` and, on enroll, the reference-photo URIs; on refresh it omits
them and the service re-reads the stored URIs. Per-photo results are returned in
the response body (FR-E4). The route is thin — it validates the request, calls
:class:`EnrollmentService`, and shapes the response; all logic lives in the
service.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from ml_service.api.deps import EnrollmentServiceDep
from ml_service.domain.models import EnrollmentResult

router = APIRouter(prefix="/v1", tags=["enrollment"])


class EnrollRequest(BaseModel):
    photo_uris: list[str] | None = Field(
        default=None,
        description=(
            "Reference-photo URIs to register then enroll. Omit to refresh from "
            "the already-stored URIs. An empty list is rejected — use DELETE to "
            "remove a student."
        ),
    )


class PhotoResultOut(BaseModel):
    index: int
    status: str
    detail: str | None = None


class EnrollResponse(BaseModel):
    school_id: str
    student_id: str
    embeddings_stored: int
    photo_results: list[PhotoResultOut]

    @classmethod
    def from_domain(cls, result: EnrollmentResult) -> EnrollResponse:
        return cls(
            school_id=result.school_id,
            student_id=result.student_id,
            embeddings_stored=result.embeddings_stored,
            photo_results=[
                PhotoResultOut(index=p.index, status=p.status.value, detail=p.detail)
                for p in result.photo_results
            ],
        )


@router.post("/schools/{school_id}/students/{student_id}/enroll")
async def enroll(
    school_id: str,
    student_id: str,
    body: EnrollRequest,
    service: EnrollmentServiceDep,
) -> EnrollResponse:
    """Enroll (with ``photo_uris``) or refresh (without) a student."""
    result = await service.enroll(school_id, student_id, body.photo_uris)
    return EnrollResponse.from_domain(result)


@router.delete(
    "/schools/{school_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_student(
    school_id: str,
    student_id: str,
    service: EnrollmentServiceDep,
) -> None:
    """Delete a student's embeddings and stored reference-photo URIs (FR-E2)."""
    await service.delete(school_id, student_id)
