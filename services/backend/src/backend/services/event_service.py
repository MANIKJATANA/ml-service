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
from backend.domain.ports import (
    EventCategoryRepository,
    EventJobProducer,
    EventRepository,
    MediaRepository,
    StudentGroupRepository,
)

_MAX_NAME_LEN = 200
_MAX_TERM_LEN = 100


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
        categories: EventCategoryRepository,
        groups: StudentGroupRepository,
    ) -> None:
        self._events = events
        self._media = media
        self._producer = producer
        self._categories = categories
        self._groups = groups

    # ---- CRUD -----------------------------------------------------------

    async def create_event(
        self,
        *,
        school_id: str,
        name: str,
        description: str | None,
        event_date: date | None,
        created_by: str | None,
        category_id: str | None = None,
        term: str | None = None,
        student_group_id: str | None = None,
    ) -> Event:
        await self._validate_category(school_id, category_id)
        await self._validate_group(school_id, student_group_id)
        return await self._events.create(
            school_id=school_id,
            name=_clean_name(name),
            description=description,
            event_date=event_date,
            created_by=created_by,
            category_id=category_id,
            term=_clean_term(term),
            student_group_id=student_group_id,
        )

    async def get_event(self, *, school_id: str, event_id: str) -> Event:
        event = await self._events.get(school_id, event_id)
        if event is None:
            raise NotFoundError(f"event not found: {event_id}")
        return event

    async def list_events(self, *, school_id: str) -> list[Event]:
        return await self._events.list_by_school(school_id)

    async def list_terms(self, *, school_id: str) -> list[str]:
        """The distinct terms this school has used (BP11b — the FE term filter)."""
        return await self._events.list_terms(school_id)

    async def update_event(
        self,
        *,
        school_id: str,
        event_id: str,
        name: str | None = None,
        description: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
        auto_notify: bool | None = None,
        category_id: str | None = None,
        term: str | None = None,
        student_group_id: str | None = None,
    ) -> Event:
        await self._validate_category(school_id, category_id)
        await self._validate_group(school_id, student_group_id)
        updated = await self._events.update(
            school_id,
            event_id,
            name=_clean_name(name) if name is not None else None,
            description=description,
            event_date=event_date,
            status=status,
            auto_notify=auto_notify,
            category_id=category_id,
            term=_clean_term(term),
            student_group_id=student_group_id,
        )
        if updated is None:
            raise NotFoundError(f"event not found: {event_id}")
        return updated

    async def _validate_category(
        self, school_id: str, category_id: str | None
    ) -> None:
        """A non-null category must belong to the caller's school — else 404, never a
        cross-tenant tag (BP11b)."""
        if category_id is None:
            return
        if await self._categories.get(school_id, category_id) is None:
            raise NotFoundError(f"category not found: {category_id}")

    async def _validate_group(
        self, school_id: str, student_group_id: str | None
    ) -> None:
        """A non-null class must belong to the caller's school — else 404, never a
        cross-tenant tag (BP11c)."""
        if student_group_id is None:
            return
        if await self._groups.get(school_id, student_group_id) is None:
            raise NotFoundError(f"class not found: {student_group_id}")

    # ---- process / redistribute ----------------------------------------

    async def process_event(self, *, school_id: str, event_id: str) -> Event:
        """Enqueue one event-level inference job (the "Process" button).

        Sets the event to `queued`; the ML worker then flips it to `processing` on pickup
        and `completed` when done (it owns those writes — decisions/0027).

        A job is enqueued only when the event is **not already in flight**: if it is
        `queued` or `processing`, this refuses — the same event must never be XADD'd twice
        (a stuck in-flight event is recovered by the queue's `XAUTOCLAIM` reclaim, not by a
        manual re-add). "Redistribute" therefore applies to a `completed` event that still
        has `pending` **or `failed`** photos (a run finished but some couldn't be
        processed): re-pressing re-enqueues and the ML worker skips the already-`completed`
        photos and re-attempts the rest — so `pending` and `failed` (BP8a) leftovers are
        re-done, idempotent. Enqueue first, then flip status — a failed enqueue (Redis down
        → `UpstreamError`→502) leaves the prior status intact.
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
        # Anything not yet `completed` is re-attempted — pending photos OR failed ones
        # (BP8a's "Retry failed"). Only refuse when there's genuinely nothing to do.
        outstanding = counts.get(MediaProcessingStatus.PENDING, 0) + counts.get(
            MediaProcessingStatus.FAILED, 0
        )
        if outstanding == 0:
            raise ValidationError("no photos to process")

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


def _clean_term(term: str | None) -> str | None:
    """Strip a term; empty → None (no term / leave unchanged on update). Caps the length."""
    if term is None:
        return None
    clean = term.strip()
    if not clean:
        return None
    if len(clean) > _MAX_TERM_LEN:
        raise ValidationError(f"term too long (max {_MAX_TERM_LEN})")
    return clean
