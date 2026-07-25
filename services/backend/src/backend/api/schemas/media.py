"""Media API schemas (decisions/0027).

The photo bytes are uploaded by the frontend directly to Supabase via a backend-minted
signed URL; the register request carries only the returned object path (never bytes).
``UploadUrlResponse`` is the same shape used for reference-photo uploads (reused).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.api.schemas.students import UploadUrlResponse
from backend.domain.models import (
    EventProcessingStatus,
    Media,
    MediaProcessingStatus,
    MediaType,
)
from backend.services.event_service import EventStatusView
from backend.services.pagination import Page

__all__ = [
    "EventStatusResponse",
    "MediaListPageResponse",
    "MediaResponse",
    "RegisterMediaRequest",
    "UploadUrlResponse",
]


class RegisterMediaRequest(BaseModel):
    """Register an already-uploaded object (records it; processing is event-level, 0027)."""

    # The bucket-relative object path returned by POST .../media/upload-url. BP17: for an
    # image the backend generates the display thumbnail from this object — the caller never
    # supplies a thumbnail path.
    storage_path: str = Field(min_length=1, max_length=1024)
    media_type: MediaType


class MediaResponse(BaseModel):
    id: str
    school_id: str
    event_id: str
    storage_path: str
    # BP17: the backend-generated display thumbnail (null for video / pre-BP17 / a failed
    # generation). The FE requests ?size=thumb only when this is set, else the full-res object.
    thumbnail_path: str | None = None
    media_type: MediaType
    processing_status: MediaProcessingStatus
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_media(cls, media: Media) -> MediaResponse:
        return cls(
            id=media.id,
            school_id=media.school_id,
            event_id=media.event_id,
            storage_path=media.storage_path,
            thumbnail_path=media.thumbnail_path,
            media_type=media.media_type,
            processing_status=media.processing_status,
            completed_at=media.completed_at,
            created_at=media.created_at,
            updated_at=media.updated_at,
        )


class MediaListPageResponse(BaseModel):
    """One page of an event's media (BP9) + the unpaginated total for the given filter."""

    items: list[MediaResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: Page[Media]) -> MediaListPageResponse:
        return cls(
            items=[MediaResponse.from_media(m) for m in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )


class EventStatusResponse(BaseModel):
    """The event-level status the FE polls + a per-photo breakdown (0027)."""

    event_id: str
    processing_status: EventProcessingStatus
    pending: int
    completed: int
    failed: int  # BP8a: photos the ML worker couldn't process (retryable via redistribute)
    total: int

    @classmethod
    def from_view(cls, view: EventStatusView) -> EventStatusResponse:
        pending = view.counts.get(MediaProcessingStatus.PENDING, 0)
        completed = view.counts.get(MediaProcessingStatus.COMPLETED, 0)
        failed = view.counts.get(MediaProcessingStatus.FAILED, 0)
        return cls(
            event_id=view.event.id,
            processing_status=view.event.processing_status,
            pending=pending,
            completed=completed,
            failed=failed,
            total=pending + completed + failed,
        )
