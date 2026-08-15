"""Event API schemas (decisions/0027)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from backend.domain.models import (
    Event,
    EventCategory,
    EventProcessingStatus,
    EventStatus,
)
from backend.services.listing_service import EventListing
from backend.services.pagination import Page


class EventCategoryResponse(BaseModel):
    """A tenant-owned event category (BP11b, decisions/0059)."""

    id: str
    name: str

    @classmethod
    def from_category(cls, c: EventCategory) -> EventCategoryResponse:
        return cls(id=c.id, name=c.name)


class CreateEventCategoryRequest(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class EventTermsResponse(BaseModel):
    """The distinct terms a school has used (BP11b — feeds the term filter dropdown)."""

    terms: list[str]


# The most events one bulk archive/restore call can carry — well above a school's event count;
# over it is a 422 (an abuse ceiling).
_MAX_BULK_EVENTS = 500


class BulkEventStatusRequest(BaseModel):
    """Archive/restore many events at once (BP13). A foreign id is silently skipped in the
    service (tenant-scoped UPDATE)."""

    event_ids: list[str] = Field(min_length=1, max_length=_MAX_BULK_EVENTS)
    status: EventStatus


class BulkEventStatusResponse(BaseModel):
    updated: int


class CreateEventRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    event_date: date | None = None
    # BP11b: the event's category (a tenant event_categories id; a foreign one → 404) + a
    # free-text term.
    category_id: str | None = Field(default=None, max_length=64)
    term: str | None = Field(default=None, max_length=100)
    # BP11c: the class this event belongs to (a tenant student_groups id; foreign → 404). None
    # = untagged (school-wide).
    student_group_id: str | None = Field(default=None, max_length=64)


class UpdateEventRequest(BaseModel):
    """Partial update; only the fields supplied are changed. (Clearing a field to
    null is not supported in v1 — 0027.)"""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    event_date: date | None = None
    status: EventStatus | None = None
    auto_notify: bool | None = None  # BP4: auto-announce to students on completion
    # BP11b/BP11c: None = leave unchanged (so term/category/class can't be cleared to null — 0027).
    category_id: str | None = Field(default=None, max_length=64)
    term: str | None = Field(default=None, max_length=100)
    student_group_id: str | None = Field(default=None, max_length=64)


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
    # BP11b: the event's term + category (category_name denormalized for display; null =
    # uncategorized).
    term: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    # BP11c: the event's class (student_group_name denormalized for display; null = untagged).
    student_group_id: str | None = None
    student_group_name: str | None = None

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
            term=event.term,
            category_id=event.category_id,
            category_name=event.category_name,
            student_group_id=event.student_group_id,
            student_group_name=event.student_group_name,
        )


class EventListItem(EventResponse):
    """An events-list row: the event + its counts (BP2). The single-item GET/POST/PATCH
    keep the leaner ``EventResponse`` — counts belong to list rows only."""

    media_count: int
    matched_students: int
    needs_review: int
    # BP19c: still-pending photos on this event — lets the list pill flag a "second batch"
    # (new photos on an already-completed event) instead of reading a stale "Completed".
    pending: int = 0

    @classmethod
    def from_listing(cls, listing: EventListing) -> EventListItem:
        return cls(
            **EventResponse.from_event(listing.event).model_dump(),
            media_count=listing.media_count,
            matched_students=listing.matched_students,
            needs_review=listing.needs_review,
            pending=listing.pending,
        )


class EventListPageResponse(BaseModel):
    """One page of the events list (BP9) + the unpaginated total for the given filter."""

    items: list[EventListItem]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: Page[EventListing]) -> EventListPageResponse:
        return cls(
            items=[EventListItem.from_listing(x) for x in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
