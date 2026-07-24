"""Event-photo routes — upload URL, register, reads (decisions/0027).

`media:upload` mints the signed URL + registers the object; `job:status:view` reads
per-photo state (both school_admin + teacher). Processing is triggered per **event** (see
`events.py` `POST /events/{id}/process`), not here — registering a photo enqueues nothing.
Tenant isolation: the school is the token's (`tenant_of`), never the URL/body — a foreign
`event_id`/`media_id` resolves to 404. The photo bytes never pass through the backend.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.pagination import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery
from backend.api.schemas.media import (
    MediaListPageResponse,
    MediaResponse,
    RegisterMediaRequest,
    UploadUrlResponse,
)
from backend.domain.models import MediaProcessingStatus, User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1", tags=["media"])

MediaUploader = Annotated[User, Depends(require_permissions(Permission.MEDIA_UPLOAD))]
StatusViewer = Annotated[User, Depends(require_permissions(Permission.JOB_STATUS_VIEW))]


@router.post("/events/{event_id}/media/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(
    event_id: str, container: ContainerDep, actor: MediaUploader
) -> UploadUrlResponse:
    signed = await container.media_service().create_upload_url(
        school_id=tenant_of(actor), event_id=event_id
    )
    return UploadUrlResponse(
        upload_url=signed.upload_url,
        object_path=signed.object_path,
        max_upload_mb=container.settings.max_upload_mb,
    )


@router.post(
    "/events/{event_id}/media",
    status_code=status.HTTP_201_CREATED,
    response_model=MediaResponse,
)
async def register_media(
    event_id: str,
    body: RegisterMediaRequest,
    container: ContainerDep,
    actor: MediaUploader,
) -> MediaResponse:
    media = await container.media_service().register_media(
        school_id=tenant_of(actor),
        event_id=event_id,
        storage_path=body.storage_path,
        media_type=body.media_type,
    )
    return MediaResponse.from_media(media)


@router.get("/events/{event_id}/media", response_model=MediaListPageResponse)
async def list_event_media(
    event_id: str,
    container: ContainerDep,
    actor: StatusViewer,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    status: Annotated[MediaProcessingStatus | None, Query()] = None,
) -> MediaListPageResponse:
    """One page of an event's media (BP9) — pagination + an optional status filter."""
    page = await container.media_service().list_event_media_page(
        school_id=tenant_of(actor),
        event_id=event_id,
        limit=limit,
        offset=offset,
        status=status,
    )
    return MediaListPageResponse.from_page(page)


@router.get("/media/{media_id}", response_model=MediaResponse)
async def get_media(
    media_id: str, container: ContainerDep, actor: StatusViewer
) -> MediaResponse:
    media = await container.media_service().get_media(
        school_id=tenant_of(actor), media_id=media_id
    )
    return MediaResponse.from_media(media)
