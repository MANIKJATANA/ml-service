"""Gallery use-cases — the distribution UX reads (decisions/0028).

Depends only on ports (no HTTP, no RBAC): authorization is at the route via
`require_permissions(gallery:view_all)` / the student-self scope, and the tenant is the
caller's token `school_id`, never the URL/body. The ML service writes `matches` (who
appears in what); this service reads it via `MlResultsReader` and joins those facts to the
backend's own students/events/media rows for all display data — `matches` stays a pure
"who-is-where" index. Grouping/filtering is in-Python: a school's event/roster is bounded
and the reads are single indexed scans; materializing student→events is deferred (0022).

Views: event→students (+counts), event→student→photos, student→events (+counts),
student→photos (optionally within one event), media→appearances, and an
entitlement-checked signed download.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from backend.domain.errors import NotFoundError
from backend.domain.models import Event, Media, SignedDownload, Student
from backend.domain.ports import (
    EventRepository,
    MediaRepository,
    MlResultsReader,
    ObjectStore,
    StudentRepository,
)


@dataclass(frozen=True, slots=True)
class StudentInEvent:
    """A student who appears in an event + how many of its photos they're in.

    ``media_count`` is derived from ``matches``; it equals the number of photos
    ``event_student_media`` actually returns only while deletes are deferred (0028 is
    archive-only). If a future phase deletes a ``media`` row but leaves its ``matches``
    rows, the count could exceed the returned photos — revisit here then."""

    student: Student
    media_count: int


@dataclass(frozen=True, slots=True)
class EventForStudent:
    """An event a student appears in + how many of its photos they're in.

    ``media_count`` is derived from ``matches`` (see ``StudentInEvent``): it tracks the
    returned-photo count only while deletes are deferred (0028)."""

    event: Event
    media_count: int


@dataclass(frozen=True, slots=True)
class MediaAppearance:
    """A student who appears in one media + that match's decision facts."""

    student: Student
    confidence: float
    needs_review: bool


class GalleryService:
    def __init__(
        self,
        reader: MlResultsReader,
        students: StudentRepository,
        events: EventRepository,
        media: MediaRepository,
        object_store: ObjectStore,
        *,
        download_url_ttl_s: int,
    ) -> None:
        self._reader = reader
        self._students = students
        self._events = events
        self._media = media
        self._object_store = object_store
        self._ttl = download_url_ttl_s

    # ---- event-centric views -------------------------------------------

    async def event_students(
        self, *, school_id: str, event_id: str
    ) -> list[StudentInEvent]:
        await self._require_event(school_id, event_id)
        appearances = await self._reader.list_event_appearances(school_id, event_id)
        counts = Counter(a.student_id for a in appearances)
        # Iterate the ordered roster, keep only appearing students -> deterministic order.
        roster = await self._students.list_by_school(school_id)
        return [
            StudentInEvent(student=s, media_count=counts[s.id])
            for s in roster
            if s.id in counts
        ]

    async def event_student_media(
        self, *, school_id: str, event_id: str, student_id: str
    ) -> list[Media]:
        await self._require_event(school_id, event_id)
        await self._require_student(school_id, student_id)
        appearances = await self._reader.list_event_appearances(school_id, event_id)
        media_ids = [a.media_id for a in appearances if a.student_id == student_id]
        return await self._media.list_by_ids(school_id, media_ids)

    # ---- student-centric views -----------------------------------------

    async def student_events(
        self, *, school_id: str, student_id: str
    ) -> list[EventForStudent]:
        await self._require_student(school_id, student_id)
        appearances = await self._reader.list_student_appearances(school_id, student_id)
        counts = Counter(a.event_id for a in appearances)
        events = await self._events.list_by_school(school_id)
        return [
            EventForStudent(event=e, media_count=counts[e.id])
            for e in events
            if e.id in counts
        ]

    async def student_media(
        self, *, school_id: str, student_id: str, event_id: str | None = None
    ) -> list[Media]:
        await self._require_student(school_id, student_id)
        if event_id is not None:
            await self._require_event(school_id, event_id)
        appearances = await self._reader.list_student_appearances(school_id, student_id)
        media_ids = [
            a.media_id
            for a in appearances
            if event_id is None or a.event_id == event_id
        ]
        return await self._media.list_by_ids(school_id, media_ids)

    # ---- media-centric view --------------------------------------------

    async def media_appearances(
        self, *, school_id: str, media_id: str
    ) -> list[MediaAppearance]:
        await self._require_media(school_id, media_id)
        appearances = await self._reader.list_media_appearances(school_id, media_id)
        roster = {s.id: s for s in await self._students.list_by_school(school_id)}
        out: list[MediaAppearance] = []
        for a in appearances:
            student = roster.get(a.student_id)
            if student is None:
                continue  # a match for a since-deleted student — skip
            out.append(
                MediaAppearance(
                    student=student,
                    confidence=a.confidence,
                    needs_review=a.needs_review,
                )
            )
        return out

    # ---- download ------------------------------------------------------

    async def download_url(
        self, *, school_id: str, media_id: str, restrict_to_student_id: str | None
    ) -> SignedDownload:
        """A short-lived signed URL to fetch one media (decisions/0028).

        ``restrict_to_student_id=None`` -> staff: any media in the school. Otherwise the
        media must be one the student appears in, else 404 — the endpoint never confirms
        the existence of a photo the student isn't entitled to see.
        """
        media = await self._require_media(school_id, media_id)
        if restrict_to_student_id is not None:
            appearances = await self._reader.list_media_appearances(school_id, media_id)
            if not any(a.student_id == restrict_to_student_id for a in appearances):
                raise NotFoundError(f"media not found: {media_id}")
        url = await self._object_store.create_signed_download_url(
            media.storage_path, expires_in_s=self._ttl
        )
        return SignedDownload(download_url=url, expires_in_s=self._ttl)

    # ---- internals ------------------------------------------------------

    async def _require_event(self, school_id: str, event_id: str) -> Event:
        event = await self._events.get(school_id, event_id)
        if event is None:
            raise NotFoundError(f"event not found: {event_id}")
        return event

    async def _require_student(self, school_id: str, student_id: str) -> Student:
        student = await self._students.get(school_id, student_id)
        if student is None:
            raise NotFoundError(f"student not found: {student_id}")
        return student

    async def _require_media(self, school_id: str, media_id: str) -> Media:
        media = await self._media.get(school_id, media_id)
        if media is None:
            raise NotFoundError(f"media not found: {media_id}")
        return media
