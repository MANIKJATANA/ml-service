"""Match-review (trust & accuracy) staff routes (BP5, decisions/0042).

Staff (`match:review`) confirm/reject an ML match, report-a-miss (add a missed student), undo
a correction, and read the per-event review lane. Tenant is the caller's token (`tenant_of`),
never the URL — a foreign id resolves to 404. The student's own "this isn't me" lives in
`me.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.review import (
    AddMissedRequest,
    MediaReviewResponse,
    SetVerdictRequest,
)
from backend.domain.models import MatchVerdict, User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1", tags=["review"])

Reviewer = Annotated[User, Depends(require_permissions(Permission.MATCH_REVIEW))]


@router.post(
    "/media/{media_id}/appearances/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def set_verdict(
    media_id: str,
    student_id: str,
    body: SetVerdictRequest,
    container: ContainerDep,
    actor: Reviewer,
) -> None:
    """Confirm or reject a match. Rejecting hides the photo from the student + blocks
    their download."""
    await container.review_service().set_verdict(
        school_id=tenant_of(actor),
        media_id=media_id,
        student_id=student_id,
        verdict=MatchVerdict(body.verdict),
        corrected_by=actor.id,
    )


@router.post(
    "/media/{media_id}/appearances", status_code=status.HTTP_204_NO_CONTENT
)
async def add_missed(
    media_id: str,
    body: AddMissedRequest,
    container: ContainerDep,
    actor: Reviewer,
) -> None:
    """Report-a-miss: add a student the ML missed to this photo (it then appears in their
    gallery). If they were already matched, this records a confirmation."""
    await container.review_service().add_missed(
        school_id=tenant_of(actor),
        media_id=media_id,
        student_id=body.student_id,
        corrected_by=actor.id,
    )


@router.delete(
    "/media/{media_id}/appearances/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def undo_correction(
    media_id: str, student_id: str, container: ContainerDep, actor: Reviewer
) -> None:
    """Undo a correction — the effective membership reverts to the raw ML truth."""
    await container.review_service().delete_correction(
        school_id=tenant_of(actor), media_id=media_id, student_id=student_id
    )


@router.get("/events/{event_id}/review", response_model=list[MediaReviewResponse])
async def event_review(
    event_id: str, container: ContainerDep, actor: Reviewer
) -> list[MediaReviewResponse]:
    """The event's ambiguous, unresolved matches grouped by photo — the review lane."""
    reviews = await container.review_service().event_review(
        school_id=tenant_of(actor), event_id=event_id
    )
    return [MediaReviewResponse.from_view(r) for r in reviews]
