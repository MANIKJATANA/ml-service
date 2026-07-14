"""Distribution use-cases — the "photos are ready" signal (BP4, decisions/0041).

Depends only on ports (no HTTP, no RBAC): authorization is at the route, tenant is the
caller's token ``school_id``. The student "new photos" signal is DERIVED (no per-student
rows written at completion — the backend has no worker at that moment): an event is
*announced* when it was manually notified OR (auto_notify AND it has completed), and a
student's photos are *unseen* until they open that event (a ``notification_reads`` upsert)
after the last announce. The matches↔events↔reads join is composed IN-PYTHON here (never a
SQL join against the isolated ``matches`` seam), mirroring ``GalleryService.student_events``.

Manual "Notify students" additionally fans out to the configured outbound channels
(best-effort); auto drives only this in-app signal (outbound-on-auto needs a future worker).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime

from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import (
    Event,
    EventStatus,
    NotificationEvent,
    Student,
)
from backend.domain.ports import (
    EventRepository,
    MatchCorrectionRepository,
    MlResultsReader,
    NotificationChannel,
    NotificationReadRepository,
    StudentRepository,
)
from backend.services.gallery_service import (
    effective_event_pairs,
    effective_student_pairs,
)


@dataclass(frozen=True, slots=True)
class StudentNotification:
    """An announced event a student appears in + whether it's still unseen."""

    event: Event
    media_count: int
    unseen: bool


@dataclass(frozen=True, slots=True)
class RosterEntry:
    """A matched student for the staff roster + whether they've opened the photos."""

    student: Student
    media_count: int
    seen: bool


@dataclass(frozen=True, slots=True)
class NotificationRoster:
    """The staff "who's been notified / seen" view for one event."""

    announced: bool
    auto_notify: bool
    notified_at: datetime | None
    entries: list[RosterEntry]


def _effective_announced_at(event: Event) -> datetime | None:
    """When the event became visible to students, or None if not announced.

    A manual notify wins (set-forward); otherwise an auto event is announced from its last
    completion. ``auto_notify`` is a live gate (turning it off un-announces an auto-only
    event) — decisions/0041."""
    if event.notified_at is not None:
        return event.notified_at
    if event.auto_notify and event.completed_at is not None:
        return event.completed_at
    return None


class NotificationService:
    def __init__(
        self,
        events: EventRepository,
        reader: MlResultsReader,
        students: StudentRepository,
        reads: NotificationReadRepository,
        notifier: NotificationChannel,
        corrections: MatchCorrectionRepository,
    ) -> None:
        self._events = events
        self._reader = reader
        self._students = students
        self._reads = reads
        self._notifier = notifier
        self._corrections = corrections

    # ---- staff: manual notify + roster ---------------------------------

    async def notify_event(self, *, school_id: str, event_id: str) -> int:
        """Announce an event's photos to the students in them, and fan out to the
        configured channels (best-effort). Returns how many students were notified."""
        event = await self._require_event(school_id, event_id)
        if event.status is not EventStatus.ACTIVE:
            raise ValidationError("event is archived")
        if event.completed_at is None:
            raise ValidationError("event has not finished processing")

        matched = await self._matched_students(school_id, event_id)
        # Stamp the announce in its own committed write FIRST, so a flaky channel can't
        # roll it back; then fan out best-effort (the composite notifier never raises).
        await self._events.mark_notified(event_id)
        for student, media_count in matched:
            await self._notifier.notify(
                NotificationEvent(
                    school_id=school_id,
                    student_id=student.id,
                    student_name=student.name,
                    contact=student.email,
                    event_id=event.id,
                    event_name=event.name,
                    event_date=event.event_date,
                    media_count=media_count,
                )
            )
        return len(matched)

    async def event_roster(
        self, *, school_id: str, event_id: str
    ) -> NotificationRoster:
        event = await self._require_event(school_id, event_id)
        effective = _effective_announced_at(event)
        reads = await self._reads.list_for_event(school_id, event_id)
        matched = await self._matched_students(school_id, event_id)
        entries = [
            RosterEntry(
                student=student,
                media_count=media_count,
                seen=_is_seen(reads.get(student.id), effective),
            )
            for student, media_count in matched
        ]
        return NotificationRoster(
            announced=effective is not None,
            auto_notify=event.auto_notify,
            notified_at=event.notified_at,
            entries=entries,
        )

    # ---- student: derived "new photos" + mark seen ---------------------

    async def student_notifications(
        self, *, school_id: str, student_id: str
    ) -> list[StudentNotification]:
        appearances = await self._reader.list_student_appearances(school_id, student_id)
        corrections = await self._corrections.list_for_student(school_id, student_id)
        # Overlay corrections (BP5, decisions/0042): a student's own "new photos" signal must
        # not count photos staff rejected for them, and must count report-a-miss additions.
        media_counts = Counter(
            eid for eid, _ in effective_student_pairs(appearances, corrections)
        )
        reads = await self._reads.list_for_student(school_id, student_id)
        events = {e.id: e for e in await self._events.list_by_school(school_id)}

        out: list[StudentNotification] = []
        for event_id, media_count in media_counts.items():
            event = events.get(event_id)
            if event is None:  # a match for a since-deleted event — skip
                continue
            effective = _effective_announced_at(event)
            if effective is None:  # not announced to students yet
                continue
            out.append(
                StudentNotification(
                    event=event,
                    media_count=media_count,
                    unseen=not _is_seen(reads.get(event_id), effective),
                )
            )
        # Newest announce first (a stable, meaningful order for the student).
        out.sort(key=lambda n: _effective_announced_at(n.event) or _MIN, reverse=True)
        return out

    async def mark_seen(
        self, *, school_id: str, student_id: str, event_id: str
    ) -> None:
        await self._require_event(school_id, event_id)
        await self._reads.mark_seen(
            school_id=school_id, student_id=student_id, event_id=event_id
        )

    # ---- internals -----------------------------------------------------

    async def _matched_students(
        self, school_id: str, event_id: str
    ) -> list[tuple[Student, int]]:
        """Students who *effectively* appear in the event ∩ the current roster (drops
        since-deleted students), each with their effective photo count — the notify targets
        + the roster. Applies the BP5 correction overlay (decisions/0042) so a staff-rejected
        student is never notified/rostered for a photo now hidden from their gallery, and a
        report-a-miss ``added`` student IS — mirroring ``GalleryService.event_students``."""
        appearances = await self._reader.list_event_appearances(school_id, event_id)
        corrections = await self._corrections.list_for_event(school_id, event_id)
        counts = Counter(sid for sid, _ in effective_event_pairs(appearances, corrections))
        roster = await self._students.list_by_school(school_id)
        return [(s, counts[s.id]) for s in roster if s.id in counts]

    async def _require_event(self, school_id: str, event_id: str) -> Event:
        event = await self._events.get(school_id, event_id)
        if event is None:
            raise NotFoundError(f"event not found: {event_id}")
        return event


def _is_seen(seen_at: datetime | None, effective_announced_at: datetime | None) -> bool:
    """Seen iff the student opened the event at/after its last announce."""
    if seen_at is None or effective_announced_at is None:
        return False
    return seen_at >= effective_announced_at


# tz-aware floor for the sort key; only ever hit if an appended event lost its announce
# time (it can't — un-announced events are skipped above), but keeps the compare tz-safe.
_MIN = datetime.min.replace(tzinfo=UTC)
