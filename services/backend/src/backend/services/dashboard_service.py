"""School command-center use-case — the admin dashboard read (BP1, decisions/0038).

Depends only on ports (no HTTP, no RBAC): authorization is at the route via
`require_permissions(dashboard:view)`, and the tenant is the caller's token `school_id`,
never the URL/body. Every number already exists in the backend's own rows (or the ML
`matches` seam it already reads) — so this is a pure read: no migration, no ML change.

One method, `school_summary`, composes a handful of grouped-count queries (one per port,
each a single indexed scan of the tenant's slice — no N+1) into the `SchoolDashboard`
value object the FE renders as stat cards + needs-attention alerts + nav scent.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import NotFoundError
from backend.domain.models import (
    EnrollmentStatus,
    EventRollup,
    MediaProcessingStatus,
    Role,
)
from backend.domain.ports import (
    EventRepository,
    MatchCorrectionRepository,
    MediaRepository,
    MlResultsReader,
    SchoolRepository,
    StudentRepository,
    UserRepository,
)


@dataclass(frozen=True, slots=True)
class SchoolDashboard:
    """A school's at-a-glance state for the admin command center (BP1).

    Plain scalar counts — the schema layer nests them for the response and the FE reads
    them into stat cards + a needs-attention block. ``events_undistributed`` and
    ``needs_review`` are the two derived "do something" signals; the enrollment-failure
    alert reuses ``students_failed``."""

    school_name: str
    # students, by enrollment status
    students_total: int
    students_enrolled: int
    students_pending: int
    students_failed: int
    # events
    events_total: int
    events_active: int
    events_archived: int
    events_processing: int
    # photos
    photos_total: int
    photos_pending: int
    # needs-attention signals
    events_undistributed: int
    needs_review: int
    # first-run setup-checklist signals (BP7a) — the two not derivable from the counts
    # above: ``has_staff`` (>=1 teacher) and ``has_distributed`` (>=1 announced event).
    has_staff: bool
    has_distributed: bool


class DashboardService:
    def __init__(
        self,
        schools: SchoolRepository,
        students: StudentRepository,
        events: EventRepository,
        media: MediaRepository,
        reader: MlResultsReader,
        corrections: MatchCorrectionRepository,
        users: UserRepository,
    ) -> None:
        self._corrections = corrections
        self._schools = schools
        self._students = students
        self._events = events
        self._media = media
        self._reader = reader
        self._users = users

    async def school_summary(self, *, school_id: str) -> SchoolDashboard:
        school = await self._schools.get(school_id)
        if school is None:  # a valid token whose school was deleted — fail closed
            raise NotFoundError(f"school not found: {school_id}")

        enrollment = await self._students.enrollment_counts(school_id)
        events = await self._events.status_counts(school_id)
        photos = await self._media.school_status_counts(school_id)
        undistributed = await self._events.count_not_started_with_media(school_id)
        # Unresolved needs-review (BP5): raw ambiguous matches minus those staff have
        # confirmed/rejected — so the alert drops as the review lane is worked. Clamped ≥ 0
        # (re-inference churn can leave a resolved match's flag stale); an approximation.
        raw_review = await self._reader.count_needs_review(school_id)
        resolved = await self._corrections.count_resolved(school_id)
        needs_review = max(0, raw_review - resolved)

        # First-run checklist (BP7a): the two step-signals not already in the counts —
        # ">=1 teacher added" and ">=1 event announced to students".
        teacher_count = await self._users.count_by_school_and_role(school_id, Role.TEACHER)
        distributed = await self._events.count_distributed(school_id)

        return _to_dashboard(
            school_name=school.name,
            enrollment=enrollment,
            events=events,
            photos=photos,
            undistributed=undistributed,
            needs_review=needs_review,
            has_staff=teacher_count >= 1,
            has_distributed=distributed >= 1,
        )


def _to_dashboard(
    *,
    school_name: str,
    enrollment: dict[EnrollmentStatus, int],
    events: EventRollup,
    photos: dict[MediaProcessingStatus, int],
    undistributed: int,
    needs_review: int,
    has_staff: bool,
    has_distributed: bool,
) -> SchoolDashboard:
    return SchoolDashboard(
        school_name=school_name,
        students_total=sum(enrollment.values()),
        students_enrolled=enrollment[EnrollmentStatus.ENROLLED],
        students_pending=enrollment[EnrollmentStatus.PENDING],
        students_failed=enrollment[EnrollmentStatus.FAILED],
        events_total=events.total,
        events_active=events.active,
        events_archived=events.archived,
        events_processing=events.processing,
        photos_total=sum(photos.values()),
        photos_pending=photos[MediaProcessingStatus.PENDING],
        events_undistributed=undistributed,
        needs_review=needs_review,
        has_staff=has_staff,
        has_distributed=has_distributed,
    )
