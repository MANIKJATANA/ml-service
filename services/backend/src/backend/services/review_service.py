"""Trust & accuracy write use-cases — the match-correction loop (BP5, decisions/0042).

Ports-only (no HTTP, no RBAC): authorization is at the route, tenant is the caller's token
``school_id``. Owns the *writes* over the backend ``match_corrections`` overlay (confirm /
reject / add-missed / student self-reject / undo) + the review-lane read; the *reads* with
the overlay applied live in ``GalleryService`` (both share the pure ``effective_*`` helper,
so "who really appears" is defined once). The ML ``matches`` are never written.

``resolves_review`` is stamped true when the corrected pair was a ``needs_review`` ML match,
so the dashboard's unresolved-review count can subtract it.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import NotFoundError
from backend.domain.models import Appearance, Event, MatchVerdict, Media, Student
from backend.domain.ports import (
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    MlResultsReader,
    StudentRepository,
)
from backend.services.gallery_service import effective_media_student_ids


@dataclass(frozen=True, slots=True)
class ReviewCandidate:
    """An ambiguous, unresolved match awaiting a staff decision."""

    student: Student
    confidence: float


@dataclass(frozen=True, slots=True)
class MediaReview:
    """One photo with the ambiguous students still needing review."""

    media: Media
    candidates: list[ReviewCandidate]


class ReviewService:
    def __init__(
        self,
        reader: MlResultsReader,
        corrections: MatchCorrectionRepository,
        media: MediaRepository,
        students: StudentRepository,
        events: EventRepository,
    ) -> None:
        self._reader = reader
        self._corrections = corrections
        self._media = media
        self._students = students
        self._events = events

    # ---- staff writes --------------------------------------------------

    async def set_verdict(
        self,
        *,
        school_id: str,
        media_id: str,
        student_id: str,
        verdict: MatchVerdict,
        corrected_by: str | None,
    ) -> None:
        """Confirm or reject a match (staff). Rejecting hides the photo from the student."""
        media = await self._require_media(school_id, media_id)
        await self._require_student(school_id, student_id)
        appearance = await self._ml_appearance(school_id, media_id, student_id)
        await self._corrections.upsert(
            school_id=school_id,
            media_id=media_id,
            student_id=student_id,
            event_id=media.event_id,
            verdict=verdict,
            corrected_by=corrected_by,
            reason=None,
            resolves_review=appearance is not None and appearance.needs_review,
        )

    async def add_missed(
        self,
        *,
        school_id: str,
        media_id: str,
        student_id: str,
        corrected_by: str | None,
    ) -> None:
        """Report-a-miss: staff add a student the ML missed. If the student is already a
        match, this is recorded as a ``confirmed`` (keeps 'an added row implies no raw
        match' clean)."""
        media = await self._require_media(school_id, media_id)
        await self._require_student(school_id, student_id)
        appearance = await self._ml_appearance(school_id, media_id, student_id)
        if appearance is not None:
            verdict = MatchVerdict.CONFIRMED
            resolves = appearance.needs_review
        else:
            verdict = MatchVerdict.ADDED
            resolves = False
        await self._corrections.upsert(
            school_id=school_id,
            media_id=media_id,
            student_id=student_id,
            event_id=media.event_id,
            verdict=verdict,
            corrected_by=corrected_by,
            reason=None,
            resolves_review=resolves,
        )

    async def delete_correction(
        self, *, school_id: str, media_id: str, student_id: str
    ) -> None:
        """Undo a correction — the effective membership reverts to the raw ML truth."""
        await self._require_media(school_id, media_id)  # tenant + existence
        await self._corrections.delete(school_id, media_id, student_id)

    # ---- student self-service ------------------------------------------

    async def self_reject(
        self, *, school_id: str, media_id: str, student_id: str, corrected_by: str | None
    ) -> None:
        """A student's "this isn't me" on their own photo. Verifies the student currently
        appears (else 404 — never confirm a photo they can't see), then records a rejection
        (overriding even a staff ``added`` — the student's "not me" wins)."""
        media = await self._require_media(school_id, media_id)
        appearances = await self._reader.list_media_appearances(school_id, media_id)
        corrections = await self._corrections.list_for_media(school_id, media_id)
        if student_id not in effective_media_student_ids(appearances, corrections):
            raise NotFoundError(f"media not found: {media_id}")
        appearance = next((a for a in appearances if a.student_id == student_id), None)
        await self._corrections.upsert(
            school_id=school_id,
            media_id=media_id,
            student_id=student_id,
            event_id=media.event_id,
            verdict=MatchVerdict.REJECTED,
            corrected_by=corrected_by,
            reason="reported_not_me",
            resolves_review=appearance is not None and appearance.needs_review,
        )

    # ---- staff review lane ---------------------------------------------

    async def event_review(
        self, *, school_id: str, event_id: str
    ) -> list[MediaReview]:
        """The ambiguous (``needs_review``) matches in an event not yet corrected, grouped
        by photo — the staff triage lane."""
        await self._require_event(school_id, event_id)
        appearances = await self._reader.list_event_appearances(school_id, event_id)
        corrected = {
            (c.media_id, c.student_id)
            for c in await self._corrections.list_for_event(school_id, event_id)
        }
        pending = [
            a
            for a in appearances
            if a.needs_review and (a.media_id, a.student_id) not in corrected
        ]
        if not pending:
            return []
        media_ids = list({a.media_id for a in pending})
        media_by_id = {
            m.id: m for m in await self._media.list_by_ids(school_id, media_ids)
        }
        roster = {s.id: s for s in await self._students.list_by_school(school_id)}
        grouped: dict[str, list[ReviewCandidate]] = {}
        for a in pending:
            student = roster.get(a.student_id)
            if a.media_id not in media_by_id or student is None:
                continue
            grouped.setdefault(a.media_id, []).append(
                ReviewCandidate(student=student, confidence=a.confidence)
            )
        return [
            MediaReview(media=media_by_id[media_id], candidates=candidates)
            for media_id, candidates in grouped.items()
        ]

    # ---- internals -----------------------------------------------------

    async def _ml_appearance(
        self, school_id: str, media_id: str, student_id: str
    ) -> Appearance | None:
        for a in await self._reader.list_media_appearances(school_id, media_id):
            if a.student_id == student_id:
                return a
        return None

    async def _require_media(self, school_id: str, media_id: str) -> Media:
        media = await self._media.get(school_id, media_id)
        if media is None:
            raise NotFoundError(f"media not found: {media_id}")
        return media

    async def _require_student(self, school_id: str, student_id: str) -> Student:
        student = await self._students.get(school_id, student_id)
        if student is None:
            raise NotFoundError(f"student not found: {student_id}")
        return student

    async def _require_event(self, school_id: str, event_id: str) -> Event:
        event = await self._events.get(school_id, event_id)
        if event is None:
            raise NotFoundError(f"event not found: {event_id}")
        return event
