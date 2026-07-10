"""Student self-scoped gallery routes (`/me`, decisions/0028).

A logged-in student sees only the events/photos they appear in. The caller's `student_id`
is resolved from the token (`gallery:view_own` via `StudentSelfScope`), never supplied —
these reuse the same `GalleryService` methods staff use, bound to the caller's own id.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.deps import ContainerDep, GalleryScope, StudentSelfScope
from backend.api.schemas.gallery import EventForStudentResponse, GalleryMediaResponse
from backend.domain.errors import AuthorizationError

router = APIRouter(prefix="/v1/me", tags=["me"])


def _student_id(scope: GalleryScope) -> str:
    # The student self-scope always binds a student_id; narrow it (fail closed).
    if scope.restrict_to_student_id is None:
        raise AuthorizationError("no student profile for this account")
    return scope.restrict_to_student_id


@router.get("/events", response_model=list[EventForStudentResponse])
async def my_events(
    container: ContainerDep, scope: StudentSelfScope
) -> list[EventForStudentResponse]:
    views = await container.gallery_service().student_events(
        school_id=scope.school_id, student_id=_student_id(scope)
    )
    return [EventForStudentResponse.from_view(v) for v in views]


@router.get("/media", response_model=list[GalleryMediaResponse])
async def my_media(
    container: ContainerDep,
    scope: StudentSelfScope,
    event_id: str | None = None,
) -> list[GalleryMediaResponse]:
    media = await container.gallery_service().student_media(
        school_id=scope.school_id, student_id=_student_id(scope), event_id=event_id
    )
    return [GalleryMediaResponse.from_media(m) for m in media]
