"""Event API schemas (decisions/0027)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from backend.domain.models import Event, EventProcessingStatus, EventStatus
from backend.services.listing_service import EventListing


class CreateEventRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    event_date: date | None = None


class UpdateEventRequest(BaseModel):
    """Partial update; only the fields supplied are changed. (Clearing a field to
    null is not supported in v1 — 0027.)"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    event_date: date | None = None
    status: EventStatus | None = None
    auto_notify: bool | None = None  # BP4: auto-announce to students on completion


class EventResponse(BaseModel):
    id: str
    school_id: str
    name: str
    description: str | None
    event_date: date | None
    status: EventStatus
    processing_status: EventProcessingStatus
    enqueued_at: datetime | None
    completed_at: datetime | None
    auto_notify: bool
    notified_at: datetime | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_event(cls, event: Event) -> EventResponse:
        return cls(
            id=event.id,
            school_id=event.school_id,
            name=event.name,
            description=event.description,
            event_date=event.event_date,
            status=event.status,
            processing_status=event.processing_status,
            enqueued_at=event.enqueued_at,
            completed_at=event.completed_at,
            auto_notify=event.auto_notify,
            notified_at=event.notified_at,
            created_at=event.created_at,
            updated_at=event.updated_at,
        )


class EventListItem(EventResponse):
    """An events-list row: the event + its counts (BP2). The single-item GET/POST/PATCH
    keep the leaner ``EventResponse`` — counts belong to list rows only."""

    media_count: int
    matched_students: int
    needs_review: int

    @classmethod
    def from_listing(cls, listing: EventListing) -> EventListItem:
        return cls(
            **EventResponse.from_event(listing.event).model_dump(),
            media_count=listing.media_count,
            matched_students=listing.matched_students,
            needs_review=listing.needs_review,
        )
