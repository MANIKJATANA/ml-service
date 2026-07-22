"""Gallery + download routes (decisions/0028).

Staff (`gallery:view_all`) browse an event's students, a student's photos in an event,
the events/photos a student appears in, and who appears in a photo. Download is
entitlement-gated via `GalleryScope` (staff: any media in the school; student: only media
they appear in). Tenant is the token's (`tenant_of`), never the URL — a foreign id
resolves to 404. Student self views live in `me.py`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import (
    ContainerDep,
    CurrentUser,
    GalleryDownloadScope,
    require_permissions,
    tenant_of,
)
from backend.api.schemas.gallery import (
    DownloadResponse,
    EventForStudentResponse,
    GalleryMediaResponse,
    MediaAppearanceResponse,
    StudentInEventResponse,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1", tags=["galleries"])

GalleryViewer = Annotated[
    User, Depends(require_permissions(Permission.GALLERY_VIEW_ALL))
]


@router.get(
    "/events/{event_id}/students", response_model=list[StudentInEventResponse]
)
async def event_students(
    event_id: str, container: ContainerDep, actor: GalleryViewer
) -> list[StudentInEventResponse]:
    views = await container.gallery_service().event_students(
        school_id=tenant_of(actor), event_id=event_id
    )
    return [StudentInEventResponse.from_view(v) for v in views]


@router.get(
    "/events/{event_id}/students/{student_id}/media",
    response_model=list[GalleryMediaResponse],
)
async def event_student_media(
    event_id: str,
    student_id: str,
    container: ContainerDep,
    actor: GalleryViewer,
) -> list[GalleryMediaResponse]:
    media = await container.gallery_service().event_student_media(
        school_id=tenant_of(actor), event_id=event_id, student_id=student_id
    )
    return [GalleryMediaResponse.from_media(m) for m in media]


@router.get(
    "/students/{student_id}/events", response_model=list[EventForStudentResponse]
)
async def student_events(
    student_id: str, container: ContainerDep, actor: GalleryViewer
) -> list[EventForStudentResponse]:
    views = await container.gallery_service().student_events(
        school_id=tenant_of(actor), student_id=student_id
    )
    return [EventForStudentResponse.from_view(v) for v in views]


@router.get(
    "/students/{student_id}/media", response_model=list[GalleryMediaResponse]
)
async def student_media(
    student_id: str,
    container: ContainerDep,
    actor: GalleryViewer,
    event_id: str | None = None,
) -> list[GalleryMediaResponse]:
    media = await container.gallery_service().student_media(
        school_id=tenant_of(actor), student_id=student_id, event_id=event_id
    )
    return [GalleryMediaResponse.from_media(m) for m in media]


@router.get(
    "/media/{media_id}/appearances", response_model=list[MediaAppearanceResponse]
)
async def media_appearances(
    media_id: str, container: ContainerDep, actor: GalleryViewer
) -> list[MediaAppearanceResponse]:
    views = await container.gallery_service().media_appearances(
        school_id=tenant_of(actor), media_id=media_id
    )
    return [MediaAppearanceResponse.from_view(v) for v in views]


@router.get("/media/{media_id}/download", response_model=DownloadResponse)
async def download_media(
    media_id: str, container: ContainerDep, scope: GalleryDownloadScope
) -> DownloadResponse:
    # Mints the signed URL used for BOTH viewing and downloading — records nothing. The
    # actual download is audited via the POST below (BP8b, decisions/0050).
    signed = await container.gallery_service().download_url(
        school_id=scope.school_id,
        media_id=media_id,
        restrict_to_student_id=scope.restrict_to_student_id,
    )
    return DownloadResponse.from_signed(signed)


@router.post("/media/{media_id}/download", status_code=204)
async def record_media_download(
    media_id: str,
    container: ContainerDep,
    scope: GalleryDownloadScope,
    actor: CurrentUser,
) -> None:
    # The FE fires this only when the user actually saves a media (BP8b) — so a view (which
    # mints via the GET above) is never logged as a download. Same entitlement gate: a caller
    # who can't download the media 404s and records nothing. `actor` reuses the already-
    # resolved (cached) current user that `scope` derived from.
    await container.gallery_service().record_download(
        school_id=scope.school_id,
        media_id=media_id,
        restrict_to_student_id=scope.restrict_to_student_id,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
