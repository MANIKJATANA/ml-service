"""Gallery use-cases — the distribution UX reads, with the BP5 correction overlay.

Depends only on ports (no HTTP, no RBAC): authorization is at the route, tenant is the
caller's token `school_id`. The ML service writes `matches` (who appears in what); this
service reads it via `MlResultsReader` and joins those facts to the backend's own rows.

BP5 (decisions/0042) overlays backend-owned `match_corrections` on every read: a
**rejected** `(media, student)` pair is removed from the effective appearances (and its
download is blocked); an **added** pair (report-a-miss) is unioned in (no ML confidence);
**confirmed** stands. The overlay is composed in-Python from the reader's appearances + the
corrections repo — never a SQL join to the isolated `matches` seam. The pure `effective_*`
helpers are shared with `ReviewService` so the "who really appears" rule lives in one place.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Appearance,
    Event,
    MatchCorrection,
    MatchVerdict,
    Media,
    SignedDownload,
    Student,
)
from backend.domain.ports import (
    DownloadAuditRepository,
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    MlResultsReader,
    ObjectStore,
    StudentRepository,
)


@dataclass(frozen=True, slots=True)
class StudentInEvent:
    """A student who appears in an event + how many of its photos they're in (effective)."""

    student: Student
    media_count: int


@dataclass(frozen=True, slots=True)
class EventForStudent:
    """An event a student appears in + how many of its photos they're in (effective)."""

    event: Event
    media_count: int


@dataclass(frozen=True, slots=True)
class MediaAppearance:
    """A student who appears in one photo + that match's decision facts + the correction
    verdict (None = an uncorrected ML match). ``confidence`` is None for an ``added``
    (staff-added) student — there is no ML score."""

    student: Student
    confidence: float | None
    needs_review: bool
    verdict: MatchVerdict | None


# ---- pure overlay helpers (shared with ReviewService + NotificationService) ----


def effective_media_student_ids(
    appearances: list[Appearance], corrections: list[MatchCorrection]
) -> set[str]:
    """The student ids who effectively appear in one media: ML matches whose verdict isn't
    ``rejected``, unioned with ``added``/``confirmed`` corrections (a ``confirmed`` stands
    even if a re-inference later dropped the raw match — staff vouched for it)."""
    by_student = {c.student_id: c for c in corrections}
    ids: set[str] = set()
    for a in appearances:
        c = by_student.get(a.student_id)
        if c is None or c.verdict is not MatchVerdict.REJECTED:
            ids.add(a.student_id)
    for student_id, c in by_student.items():
        if c.verdict in (MatchVerdict.ADDED, MatchVerdict.CONFIRMED):
            ids.add(student_id)
    return ids


def effective_event_pairs(
    appearances: list[Appearance], corrections: list[MatchCorrection]
) -> list[tuple[str, str]]:
    """(student_id, media_id) pairs that effectively appear across an event."""
    rejected = {
        (c.media_id, c.student_id)
        for c in corrections
        if c.verdict is MatchVerdict.REJECTED
    }
    pairs = [
        (a.student_id, a.media_id)
        for a in appearances
        if (a.media_id, a.student_id) not in rejected
    ]
    seen = set(pairs)
    for c in corrections:
        if c.verdict is MatchVerdict.ADDED and (c.student_id, c.media_id) not in seen:
            pairs.append((c.student_id, c.media_id))
    return pairs


def effective_student_pairs(
    appearances: list[Appearance], corrections: list[MatchCorrection]
) -> list[tuple[str, str]]:
    """(event_id, media_id) pairs a student effectively appears in."""
    rejected_media = {
        c.media_id for c in corrections if c.verdict is MatchVerdict.REJECTED
    }
    pairs = [
        (a.event_id, a.media_id)
        for a in appearances
        if a.media_id not in rejected_media
    ]
    seen_media = {media_id for _, media_id in pairs}
    for c in corrections:
        if c.verdict is MatchVerdict.ADDED and c.media_id not in seen_media:
            pairs.append((c.event_id, c.media_id))
    return pairs


class GalleryService:
    def __init__(
        self,
        reader: MlResultsReader,
        students: StudentRepository,
        events: EventRepository,
        media: MediaRepository,
        corrections: MatchCorrectionRepository,
        object_store: ObjectStore,
        audit: DownloadAuditRepository,
        *,
        download_url_ttl_s: int,
    ) -> None:
        self._reader = reader
        self._students = students
        self._events = events
        self._media = media
        self._corrections = corrections
        self._object_store = object_store
        self._audit = audit
        self._ttl = download_url_ttl_s

    # ---- event-centric views -------------------------------------------

    async def event_students(
        self, *, school_id: str, event_id: str
    ) -> list[StudentInEvent]:
        await self._require_event(school_id, event_id)
        appearances = await self._reader.list_event_appearances(school_id, event_id)
        corrections = await self._corrections.list_for_event(school_id, event_id)
        pairs = effective_event_pairs(appearances, corrections)
        counts = Counter(student_id for student_id, _ in pairs)
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
        corrections = await self._corrections.list_for_event(school_id, event_id)
        pairs = effective_event_pairs(appearances, corrections)
        media_ids = [m for s, m in pairs if s == student_id]
        return await self._media.list_by_ids(school_id, media_ids)

    # ---- student-centric views -----------------------------------------

    async def student_events(
        self, *, school_id: str, student_id: str
    ) -> list[EventForStudent]:
        await self._require_student(school_id, student_id)
        appearances = await self._reader.list_student_appearances(school_id, student_id)
        corrections = await self._corrections.list_for_student(school_id, student_id)
        pairs = effective_student_pairs(appearances, corrections)
        counts = Counter(event_id for event_id, _ in pairs)
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
        corrections = await self._corrections.list_for_student(school_id, student_id)
        pairs = effective_student_pairs(appearances, corrections)
        media_ids = [m for e, m in pairs if event_id is None or e == event_id]
        return await self._media.list_by_ids(school_id, media_ids)

    # ---- media-centric view (staff photo detail + the review surface) --

    async def media_appearances(
        self, *, school_id: str, media_id: str
    ) -> list[MediaAppearance]:
        await self._require_media(school_id, media_id)
        appearances = await self._reader.list_media_appearances(school_id, media_id)
        corrections = {
            c.student_id: c
            for c in await self._corrections.list_for_media(school_id, media_id)
        }
        roster = {s.id: s for s in await self._students.list_by_school(school_id)}
        # This is the staff-only review surface (gallery:view_all) — so it shows EVERY
        # match, including ``rejected`` ones (with the verdict), so staff can see + undo
        # a rejection. The student-facing reads (student_*/event_students/download) exclude
        # rejected via the effective-pair helpers above.
        out: list[MediaAppearance] = []
        matched_ids: set[str] = set()
        for a in appearances:
            c = corrections.get(a.student_id)
            student = roster.get(a.student_id)
            if student is None:
                continue  # match for a since-deleted student
            matched_ids.add(a.student_id)
            out.append(
                MediaAppearance(
                    student=student,
                    confidence=a.confidence,
                    needs_review=a.needs_review,
                    verdict=c.verdict if c is not None else None,
                )
            )
        # Added students (report-a-miss) not already an ML match.
        for student_id, c in corrections.items():
            if c.verdict is MatchVerdict.ADDED and student_id not in matched_ids:
                student = roster.get(student_id)
                if student is None:
                    continue
                out.append(
                    MediaAppearance(
                        student=student,
                        confidence=None,
                        needs_review=False,
                        verdict=MatchVerdict.ADDED,
                    )
                )
        return out

    # ---- download ------------------------------------------------------

    async def download_url(
        self, *, school_id: str, media_id: str, restrict_to_student_id: str | None
    ) -> SignedDownload:
        """A short-lived signed URL to fetch one media (decisions/0028 + BP5).

        This mint is used for BOTH viewing (the browser renders the image/video off this
        URL) and the download action, so it records **nothing** — the actual download is
        audited separately via ``record_download`` (BP8b, decisions/0050), fired only when
        the user saves, so a mere view is never logged as a download.

        ``restrict_to_student_id=None`` -> staff (any media in the school). Otherwise the
        media must be one the student **effectively** appears in (an un-rejected ML match or
        an ``added`` correction), else 404 — a rejected match blocks the download."""
        media = await self._require_media(school_id, media_id)
        await self._require_downloadable(school_id, media_id, restrict_to_student_id)
        url = await self._object_store.create_signed_download_url(
            media.storage_path, expires_in_s=self._ttl
        )
        return SignedDownload(download_url=url, expires_in_s=self._ttl)

    async def record_download(
        self,
        *,
        school_id: str,
        media_id: str,
        restrict_to_student_id: str | None,
        actor_user_id: str,
        actor_role: str,
    ) -> None:
        """Record one **actual** media download in the audit (BP8b, decisions/0050) — fired
        on the download action (the user clicked save), NOT on the signed-URL mint (which is
        shared with viewing). Runs the same entitlement gate as ``download_url``, so a caller
        who can't download the media 404s and records nothing. ``subject_student_id`` is the
        downloading student's own id on a self-download (None for staff)."""
        media = await self._require_media(school_id, media_id)
        await self._require_downloadable(school_id, media_id, restrict_to_student_id)
        await self._audit.record(
            school_id=school_id,
            media_id=media_id,
            event_id=media.event_id,
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            subject_student_id=restrict_to_student_id,
        )

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

    async def _require_downloadable(
        self, school_id: str, media_id: str, restrict_to_student_id: str | None
    ) -> None:
        """The download entitlement gate (shared by ``download_url`` + ``record_download``):
        staff (``None``) may fetch any in-school media; a student only media they
        **effectively** appear in (an un-rejected match or an ``added`` correction), else 404
        — a rejected match blocks it, and it never confirms a photo they can't see."""
        if restrict_to_student_id is None:
            return
        appearances = await self._reader.list_media_appearances(school_id, media_id)
        corrections = await self._corrections.list_for_media(school_id, media_id)
        if restrict_to_student_id not in effective_media_student_ids(
            appearances, corrections
        ):
            raise NotFoundError(f"media not found: {media_id}")
