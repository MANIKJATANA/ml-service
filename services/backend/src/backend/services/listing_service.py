"""List-enrichment use-cases — count-rich admin lists (BP2, decisions/0039).

Depends only on ports (no HTTP, no RBAC): authorization is at the route, and the tenant
is the caller's token ``school_id`` (never the URL) for school-scoped lists. Isolated
here — rather than threading the ML ``matches`` reader into every write service — this
composes each list's rows with the batch grouped counts they need. Every count is one
indexed scan of a tenant's slice (or a batch grouped scan for the platform rollups), zipped
to the rows in-Python: **no N+1**. Pure reads — no migration, no ML change.

Views: events + per-event counts, students + per-student counts, and (platform) schools +
per-school rollups + a school's administrator roster.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.domain.errors import NotFoundError
from backend.domain.models import (
    Event,
    Role,
    School,
    SchoolRollup,
    Student,
    User,
)
from backend.domain.ports import (
    EventRepository,
    MediaRepository,
    MlResultsReader,
    SchoolRepository,
    StudentRepository,
    UserRepository,
)


@dataclass(frozen=True, slots=True)
class EventListing:
    """An event + the counts the events list shows (photos, who matched)."""

    event: Event
    media_count: int
    matched_students: int
    needs_review: int


@dataclass(frozen=True, slots=True)
class StudentListing:
    """A student + how many photos/events they appear in."""

    student: Student
    appearance_count: int
    event_count: int


@dataclass(frozen=True, slots=True)
class SchoolListing:
    """A school + its rollup (admins, teachers, students, events)."""

    school: School
    rollup: SchoolRollup


class ListingService:
    def __init__(
        self,
        schools: SchoolRepository,
        users: UserRepository,
        students: StudentRepository,
        events: EventRepository,
        media: MediaRepository,
        reader: MlResultsReader,
    ) -> None:
        self._schools = schools
        self._users = users
        self._students = students
        self._events = events
        self._media = media
        self._reader = reader

    # ---- school-scoped lists -------------------------------------------

    async def list_events(self, *, school_id: str) -> list[EventListing]:
        events = await self._events.list_by_school(school_id)
        media_counts = await self._media.counts_by_event(school_id)
        match_counts = await self._reader.event_match_counts(school_id)
        out: list[EventListing] = []
        for e in events:
            m = match_counts.get(e.id)
            out.append(
                EventListing(
                    event=e,
                    media_count=media_counts.get(e.id, 0),
                    matched_students=m.matched_students if m else 0,
                    needs_review=m.needs_review if m else 0,
                )
            )
        return out

    async def list_students(self, *, school_id: str) -> list[StudentListing]:
        students = await self._students.list_by_school(school_id)
        appearance_counts = await self._reader.student_appearance_counts(school_id)
        out: list[StudentListing] = []
        for s in students:
            c = appearance_counts.get(s.id)
            out.append(
                StudentListing(
                    student=s,
                    appearance_count=c.appearance_count if c else 0,
                    event_count=c.event_count if c else 0,
                )
            )
        return out

    # ---- platform (cross-tenant) ---------------------------------------

    async def list_schools(self) -> list[SchoolListing]:
        schools = await self._schools.list_all()
        role_counts = await self._users.role_counts_by_school()
        students_by_school = await self._students.counts_by_school()
        events_by_school = await self._events.counts_by_school()
        return [
            SchoolListing(
                school=s,
                rollup=_rollup(
                    s.id, role_counts, students_by_school, events_by_school
                ),
            )
            for s in schools
        ]

    async def get_school(self, *, school_id: str) -> SchoolListing:
        school = await self._schools.get(school_id)
        if school is None:
            raise NotFoundError(f"school not found: {school_id}")
        role_counts = await self._users.role_counts_by_school()
        students_by_school = await self._students.counts_by_school()
        events_by_school = await self._events.counts_by_school()
        return SchoolListing(
            school=school,
            rollup=_rollup(
                school.id, role_counts, students_by_school, events_by_school
            ),
        )

    async def list_school_admins(self, *, school_id: str) -> list[User]:
        school = await self._schools.get(school_id)
        if school is None:
            raise NotFoundError(f"school not found: {school_id}")
        return await self._users.list_by_school_and_role(school_id, Role.SCHOOL_ADMIN)


def _rollup(
    school_id: str,
    role_counts: dict[str, dict[Role, int]],
    students_by_school: dict[str, int],
    events_by_school: dict[str, int],
) -> SchoolRollup:
    roles = role_counts.get(school_id, {})
    return SchoolRollup(
        admins=roles.get(Role.SCHOOL_ADMIN, 0),
        teachers=roles.get(Role.TEACHER, 0),
        students=students_by_school.get(school_id, 0),
        events=events_by_school.get(school_id, 0),
    )
