"""List-enrichment use-cases — count-rich admin lists (BP2, decisions/0039).

Depends only on ports (no HTTP, no RBAC): authorization is at the route, and the tenant
is the caller's token ``school_id`` (never the URL) for school-scoped lists. Isolated
here — rather than threading the ML ``matches`` reader into every write service — this
composes each list's rows with the batch grouped counts they need. Every count is one
indexed scan of a tenant's slice (or a batch grouped scan for the platform rollups), zipped
to the rows in-Python: **no N+1**. Pure reads — no migration, no ML change.

Views: events + per-event counts, students + per-student counts, and (platform) schools +
per-school rollups + a school's administrator roster.

Divergence (deliberate, BP5/decisions/0042): these list counts are **raw ML** — they do
NOT apply the ``match_corrections`` overlay. The galleries (``GalleryService``) are the
effective source of truth; a staff-rejected match still counts here until reconciliation
is a dedicated follow-up. So an events/students list may show one more "matched" than the
gallery after a rejection. Kept raw for v1 (small early correction volume; no N+1 overlay
batch here yet).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date

from backend.domain.errors import NotFoundError
from backend.domain.models import (
    EVENT_COUNT_SORTS,
    SCHOOL_COUNT_SORTS,
    STUDENT_COUNT_SORTS,
    EnrollmentStatus,
    Event,
    EventMatchCounts,
    EventSort,
    EventStatus,
    Role,
    School,
    SchoolRollup,
    SchoolSort,
    Student,
    StudentAppearanceCounts,
    StudentSort,
    User,
    UserSort,
)
from backend.domain.ports import (
    EventRepository,
    MediaRepository,
    MlResultsReader,
    SchoolRepository,
    StudentRepository,
    UserRepository,
)
from backend.services.pagination import Page


@dataclass(frozen=True, slots=True)
class EventListing:
    """An event + the counts the events list shows (photos, who matched)."""

    event: Event
    media_count: int
    matched_students: int
    needs_review: int
    # BP19c: still-`pending` photos — lets the list pill flag a "second batch" (new photos on
    # an already-`completed` event) that the raw event processing_status would read "Completed".
    pending: int = 0


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


# ---- BP9 count-sort helpers (decisions/0055) ----------------------------
#
# A "count column" sort (e.g. students by most-photos) can't be paged in SQL — the order
# depends on a count that lives in the isolated ML ``matches`` seam (never SQL-joined) or a
# sibling aggregate. So the service fetches ALL matching ids (``list_ids``, id-only, bounded
# by the tenant slice), sorts them in-Python off a school-wide count dict (the same grouped
# query BP2 already runs), slices one page, then hydrates only that page (``list_by_ids``).
# Row-native sorts (name/date) never touch this — they page directly in SQL.


def _count_sorted_page(
    ids: list[str],
    *,
    key: Callable[[str], int],
    descending: bool,
    offset: int,
    limit: int,
) -> list[str]:
    """Sort ids by a count ``key`` (id as a stable tiebreak, so pages never overlap),
    honoring direction, then slice one page. Mutates ``ids`` (a fresh list per call)."""
    ids.sort(key=lambda i: (key(i), i), reverse=descending)
    return ids[offset : offset + limit]


def _student_listing(
    student: Student, counts: dict[str, StudentAppearanceCounts]
) -> StudentListing:
    c = counts.get(student.id)
    return StudentListing(
        student=student,
        appearance_count=c.appearance_count if c else 0,
        event_count=c.event_count if c else 0,
    )


def _event_listing(
    event: Event,
    media_counts: dict[str, int],
    match_counts: dict[str, EventMatchCounts],
    pending_counts: dict[str, int],
) -> EventListing:
    m = match_counts.get(event.id)
    return EventListing(
        event=event,
        media_count=media_counts.get(event.id, 0),
        matched_students=m.matched_students if m else 0,
        needs_review=m.needs_review if m else 0,
        pending=pending_counts.get(event.id, 0),
    )


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
        pending_counts = await self._media.pending_counts_by_event(school_id)
        match_counts = await self._reader.event_match_counts(school_id)
        return [
            _event_listing(e, media_counts, match_counts, pending_counts) for e in events
        ]

    async def list_events_page(
        self,
        *,
        school_id: str,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: EventSort = EventSort.EVENT_DATE,
        descending: bool = True,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> Page[EventListing]:
        """One page of the events list (BP9), searched/filtered/sorted server-side. Count
        sorts (media/matched/needs_review) take the whole-list id-scan path; row-native
        sorts page directly in SQL. BP11b: ``category_id``/``term`` filter + ``date_from``/
        ``date_to`` bound ``event_date`` (the calendar month window). BP11c: ``student_group_id``
        filters to one class; ``scope_group_ids`` is a teacher's focus (their classes + untagged
        events) — all threaded through both paths."""
        media_counts = await self._media.counts_by_event(school_id)
        pending_counts = await self._media.pending_counts_by_event(school_id)
        match_counts = await self._reader.event_match_counts(school_id)
        if sort in EVENT_COUNT_SORTS:
            ids = await self._events.list_ids(
                school_id,
                q=q,
                status=status,
                category_id=category_id,
                term=term,
                date_from=date_from,
                date_to=date_to,
                student_group_id=student_group_id,
                scope_group_ids=scope_group_ids,
            )
            total = len(ids)

            def key(eid: str) -> int:
                if sort is EventSort.MEDIA_COUNT:
                    return media_counts.get(eid, 0)
                m = match_counts.get(eid)
                if m is None:
                    return 0
                return (
                    m.matched_students
                    if sort is EventSort.MATCHED_STUDENTS
                    else m.needs_review
                )

            page_ids = _count_sorted_page(
                ids, key=key, descending=descending, offset=offset, limit=limit
            )
            by_id = {
                e.id: e for e in await self._events.list_by_ids(school_id, page_ids)
            }
            events = [by_id[eid] for eid in page_ids if eid in by_id]
        else:
            events = await self._events.list_page(
                school_id,
                limit=limit,
                offset=offset,
                q=q,
                sort=sort,
                descending=descending,
                status=status,
                category_id=category_id,
                term=term,
                date_from=date_from,
                date_to=date_to,
                student_group_id=student_group_id,
                scope_group_ids=scope_group_ids,
            )
            total = await self._events.count_page(
                school_id,
                q=q,
                status=status,
                category_id=category_id,
                term=term,
                date_from=date_from,
                date_to=date_to,
                student_group_id=student_group_id,
                scope_group_ids=scope_group_ids,
            )
        items = [
            _event_listing(e, media_counts, match_counts, pending_counts) for e in events
        ]
        return Page(items=items, total=total, limit=limit, offset=offset)

    async def list_students(self, *, school_id: str) -> list[StudentListing]:
        students = await self._students.list_by_school(school_id)
        appearance_counts = await self._reader.student_appearance_counts(school_id)
        return [_student_listing(s, appearance_counts) for s in students]

    async def list_students_page(
        self,
        *,
        school_id: str,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: StudentSort = StudentSort.NAME,
        descending: bool = False,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> Page[StudentListing]:
        """One page of the students list (BP9). Count sorts (appearance/event) take the
        whole-list id-scan path; row-native sorts page directly in SQL. BP11a:
        ``student_group_id`` filters to one class. BP11c: ``scope_group_ids`` is a teacher's
        focus (limit to their classes) — both threaded through both paths."""
        counts = await self._reader.student_appearance_counts(school_id)
        if sort in STUDENT_COUNT_SORTS:
            ids = await self._students.list_ids(
                school_id,
                q=q,
                status=status,
                student_group_id=student_group_id,
                scope_group_ids=scope_group_ids,
            )
            total = len(ids)

            def key(sid: str) -> int:
                c = counts.get(sid)
                if c is None:
                    return 0
                return (
                    c.appearance_count
                    if sort is StudentSort.APPEARANCE_COUNT
                    else c.event_count
                )

            page_ids = _count_sorted_page(
                ids, key=key, descending=descending, offset=offset, limit=limit
            )
            by_id = {
                s.id: s for s in await self._students.list_by_ids(school_id, page_ids)
            }
            students = [by_id[sid] for sid in page_ids if sid in by_id]
        else:
            students = await self._students.list_page(
                school_id,
                limit=limit,
                offset=offset,
                q=q,
                sort=sort,
                descending=descending,
                status=status,
                student_group_id=student_group_id,
                scope_group_ids=scope_group_ids,
            )
            total = await self._students.count_page(
                school_id,
                q=q,
                status=status,
                student_group_id=student_group_id,
                scope_group_ids=scope_group_ids,
            )
        items = [_student_listing(s, counts) for s in students]
        return Page(items=items, total=total, limit=limit, offset=offset)

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

    async def list_schools_page(
        self,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: SchoolSort = SchoolSort.NAME,
        descending: bool = False,
    ) -> Page[SchoolListing]:
        """One page of the platform schools list (BP9). The rollup counts live on
        backend-owned tables (no ML seam); count sorts still use the id-scan path for a
        uniform contract with students/events."""
        role_counts = await self._users.role_counts_by_school()
        students_by_school = await self._students.counts_by_school()
        events_by_school = await self._events.counts_by_school()

        def rollup_of(school_id: str) -> SchoolRollup:
            return _rollup(school_id, role_counts, students_by_school, events_by_school)

        if sort in SCHOOL_COUNT_SORTS:
            ids = await self._schools.list_ids(q=q)
            total = len(ids)

            def key(scid: str) -> int:
                r = rollup_of(scid)
                if sort is SchoolSort.STUDENTS:
                    return r.students
                if sort is SchoolSort.EVENTS:
                    return r.events
                if sort is SchoolSort.TEACHERS:
                    return r.teachers
                return r.admins

            page_ids = _count_sorted_page(
                ids, key=key, descending=descending, offset=offset, limit=limit
            )
            by_id = {s.id: s for s in await self._schools.list_by_ids(page_ids)}
            schools = [by_id[scid] for scid in page_ids if scid in by_id]
        else:
            schools = await self._schools.list_page(
                limit=limit, offset=offset, q=q, sort=sort, descending=descending
            )
            total = await self._schools.count_page(q=q)
        items = [
            SchoolListing(school=s, rollup=rollup_of(s.id)) for s in schools
        ]
        return Page(items=items, total=total, limit=limit, offset=offset)

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

    async def list_school_admins_page(
        self,
        *,
        school_id: str,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: UserSort = UserSort.CREATED_AT,
        descending: bool = True,
    ) -> Page[User]:
        """One page of a school's administrator roster (BP9). Searched on email + sorted
        server-side (users have no name/count columns)."""
        school = await self._schools.get(school_id)
        if school is None:
            raise NotFoundError(f"school not found: {school_id}")
        users = await self._users.list_page_by_role(
            school_id,
            Role.SCHOOL_ADMIN,
            limit=limit,
            offset=offset,
            q=q,
            sort=sort,
            descending=descending,
        )
        total = await self._users.count_page_by_role(
            school_id, Role.SCHOOL_ADMIN, q=q
        )
        return Page(items=users, total=total, limit=limit, offset=offset)


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
