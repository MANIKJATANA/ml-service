"""Per-student engagement use-case (BP23, decisions/0078).

A staff-facing read (``student:manage``) composing one student's reach + engagement from the
backend's own signals: the events/photos they *effectively* appear in (the BP5 correction
overlay, composed in-Python off the ML ``matches`` seam — never a SQL join), how many
distributions they've opened (``notification_reads``), and their own saves (``download_audit``).

Its OWN endpoint (not fields on ``StudentResponse``) so the write-path response stays frozen
and these three reads never load on a cheap create/patch. Depends only on ports (no HTTP, no
RBAC): authorization is at the route, tenant is the caller's token ``school_id``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.domain.errors import NotFoundError
from backend.domain.ports import (
    DownloadAuditRepository,
    MatchCorrectionRepository,
    MlResultsReader,
    NotificationReadRepository,
    StudentRepository,
)
from backend.services.gallery_service import effective_student_pairs


@dataclass(frozen=True, slots=True)
class StudentEngagement:
    """One student's reach + engagement (BP23). Reach = the events/photos they effectively
    appear in; engagement = distinct events opened + last-open time + their own saves.

    ``events_opened`` counts distinct events with a read row (``notification_reads`` is
    per-(student, event), so there's no per-photo "opened" — a documented coarseness)."""

    events_appearing: int
    photos_appearing: int
    events_opened: int
    last_opened_at: datetime | None
    downloads: int


class EngagementService:
    def __init__(
        self,
        students: StudentRepository,
        reader: MlResultsReader,
        corrections: MatchCorrectionRepository,
        reads: NotificationReadRepository,
        audit: DownloadAuditRepository,
    ) -> None:
        self._students = students
        self._reader = reader
        self._corrections = corrections
        self._reads = reads
        self._audit = audit

    async def student_engagement(
        self, *, school_id: str, student_id: str
    ) -> StudentEngagement:
        # Tenant-scoped: a foreign/unknown student is a 404 before any composition.
        student = await self._students.get(school_id, student_id)
        if student is None:
            raise NotFoundError(f"student not found: {student_id}")

        # Reach: the events/photos they EFFECTIVELY appear in (BP5 overlay — drop rejected,
        # union added), composed in-Python off the ML seam (never a SQL join).
        appearances = await self._reader.list_student_appearances(school_id, student_id)
        corrections = await self._corrections.list_for_student(school_id, student_id)
        pairs = effective_student_pairs(appearances, corrections)  # (event_id, media_id)
        events_appearing = len({event_id for event_id, _ in pairs})
        photos_appearing = len({media_id for _, media_id in pairs})

        # Engagement: distinct events opened + the most recent open (notification_reads).
        reads = await self._reads.list_for_student(school_id, student_id)
        events_opened = len(reads)
        last_opened_at = max(reads.values(), default=None)

        # Their own saves (download_audit; subject_student_id-scoped self-downloads).
        downloads = await self._audit.count_recent(school_id, student_id=student_id)

        return StudentEngagement(
            events_appearing=events_appearing,
            photos_appearing=photos_appearing,
            events_opened=events_opened,
            last_opened_at=last_opened_at,
            downloads=downloads,
        )
