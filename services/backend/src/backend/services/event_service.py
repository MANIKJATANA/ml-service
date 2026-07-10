"""Event use-cases (decisions/0027).

Depends only on ports (no HTTP, no RBAC): authorization is enforced at the route via
`require_permissions(...)` and the tenant is the caller's token `school_id`, never the
URL/body. `process_event` (the "Process" / "redistribute" button) enqueues one event-level
job and sets the event's `processing_status` to `queued`; the **ML worker** then advances
it to `processing`/`completed` (it owns those writes — decisions/0027). v1 archives (not
deletes) an event.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    Event,
    EventJob,
    EventProcessingStatus,
    EventStatus,
    MediaProcessingStatus,
)
from backend.domain.ports import EventJobProducer, EventRepository, MediaRepository

_MAX_NAME_LEN = 200


@dataclass(frozen=True, slots=True)
class EventStatusView:
    """An event's poll-able status: the event-level state + a per-photo breakdown."""

    event: Event
    counts: dict[MediaProcessingStatus, int]


class EventService:
    def __init__(
        self,
        events: EventRepository,
        media: MediaRepository,
        producer: EventJobProducer,
    ) -> None:
        self._events = events
        self._media = media
        self._producer = producer

    # ---- CRUD -----------------------------------------------------------

    async def create_event(
        self,
        *,
        school_id: str,
        name: str,
        description: str | None,
        event_date: date | None,
        created_by: str | None,
    ) -> Event:
        return await self._events.create(
            school_id=school_id,
            name=_clean_name(name),
            description=description,
            event_date=event_date,
            created_by=created_by,
        )

    async def get_event(self, *, school_id: str, event_id: str) -> Event:
        event = await self._events.get(school_id, event_id)
        if event is None:
            raise NotFoundError(f"event not found: {event_id}")
        return event

    async def list_events(self, *, school_id: str) -> list[Event]:
        return await self._events.list_by_school(school_id)

    async def update_event(
        self,
        *,
        school_id: str,
        event_id: str,
        name: str | None = None,
        description: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
    ) -> Event:
        updated = await self._events.update(
            school_id,
            event_id,
            name=_clean_name(name) if name is not None else None,
            description=description,
            event_date=event_date,
            status=status,
        )
        if updated is None:
            raise NotFoundError(f"event not found: {event_id}")
        return updated

    # ---- process / redistribute ----------------------------------------

    async def process_event(self, *, school_id: str, event_id: str) -> Event:
        """Enqueue one event-level inference job (the "Process" button).

        Sets the event to `queued`; the ML worker then flips it to `processing` on pickup
        and `completed` when done (it owns those writes — decisions/0027).

        A job is enqueued only when the event is **not already in flight**: if it is
        `queued` or `processing`, this refuses — the same event must never be XADD'd twice
        (a stuck in-flight event is recovered by the queue's `XAUTOCLAIM` reclaim, not by a
        manual re-add). "Redistribute" therefore applies to a `completed` event that still
        has `pending` photos (a run finished but some photos couldn't be processed):
        re-pressing re-enqueues and the ML worker skips the already-`completed` photos, so
        only the leftovers are re-done — idempotent. Enqueue first, then flip status — a
        failed enqueue (Redis down → `UpstreamError`→502) leaves the prior status intact.
        """
        event = await self.get_event(school_id=school_id, event_id=event_id)
        if event.status is not EventStatus.ACTIVE:
            raise ValidationError("event is archived")
        if event.processing_status in (
            EventProcessingStatus.QUEUED,
            EventProcessingStatus.PROCESSING,
        ):
            # Already on the stream / being worked — never enqueue a duplicate job.
            raise ValidationError("event is already queued or processing")

        counts = await self._media.status_counts(school_id, event_id)
        if counts.get(MediaProcessingStatus.PENDING, 0) == 0:
            # Nothing to do: no photos, or every photo already processed.
            raise ValidationError("no pending photos to process")

        await self._producer.enqueue(EventJob(school_id=school_id, event_id=event_id))
        await self._events.set_processing(
            event_id, status=EventProcessingStatus.QUEUED
        )
        return await self.get_event(school_id=school_id, event_id=event_id)

    async def event_status(
        self, *, school_id: str, event_id: str
    ) -> EventStatusView:
        event = await self.get_event(school_id=school_id, event_id=event_id)
        counts = await self._media.status_counts(school_id, event_id)
        return EventStatusView(event=event, counts=counts)


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not clean or len(clean) > _MAX_NAME_LEN:
        raise ValidationError("event name must be 1-200 characters")
    return clean
