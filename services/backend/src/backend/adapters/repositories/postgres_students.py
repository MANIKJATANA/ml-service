"""Postgres implementation of :class:`StudentRepository` (decisions/0026).

Reads are tenant-scoped: every ``get``/``list`` takes ``school_id`` so a student
that belongs to another school is invisible (returned as ``None``/absent), enforcing
tenant isolation at the query layer (decisions/0022). Each read JOINs ``users`` to
carry the student's login ``email`` on the read model (decisions/0033) and LEFT JOINs
``student_groups`` to carry the class name for list display (BP11a, decisions/0058).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, Select, false, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import (
    LIKE_ESCAPE,
    ilike_term,
    opt_uuid,
    req_uuid,
)
from backend.db.models import Student as StudentRow
from backend.db.models import StudentGroup as StudentGroupRow
from backend.db.models import User as UserRow
from backend.domain.errors import NotFoundError
from backend.domain.models import (
    EnrollmentFailureReason,
    EnrollmentStatus,
    Student,
    StudentSort,
)

# Row-native sort columns (BP9). Count-column sorts (appearance/event) never reach the
# adapter — the service takes the id-scan path for those — so a stray one falls back to
# ``created_at`` defensively.
_SORT_COLS = {
    StudentSort.NAME: StudentRow.name,
    StudentSort.CREATED_AT: StudentRow.created_at,
}


def _to_student(row: StudentRow, email: str, group_name: str | None = None) -> Student:
    return Student(
        id=str(row.id),
        school_id=str(row.school_id),
        user_id=str(row.user_id),
        name=row.name,
        email=email,
        reference_photo_path=row.reference_photo_path,
        enrollment_status=EnrollmentStatus(row.enrollment_status),
        created_at=row.created_at,
        updated_at=row.updated_at,
        enrollment_failure_reason=(
            EnrollmentFailureReason(row.enrollment_failure_reason)
            if row.enrollment_failure_reason is not None
            else None
        ),
        reference_photo_thumbnail_path=row.reference_photo_thumbnail_path,
        student_group_id=(
            str(row.student_group_id) if row.student_group_id is not None else None
        ),
        student_group_name=group_name,
    )


class PostgresStudentRepository:
    """``StudentRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    @staticmethod
    def _select_with_email_and_class() -> Select[tuple[StudentRow, str, str]]:
        """The base read: student + login email (INNER) + class name (LEFT, nullable).

        Returned rows are ``(StudentRow, email, group_name)`` — ``group_name`` is ``None``
        for an un-classed student (the LEFT JOIN miss)."""
        return (
            select(StudentRow, UserRow.email, StudentGroupRow.name)
            .join(UserRow, StudentRow.user_id == UserRow.id)
            .outerjoin(
                StudentGroupRow, StudentRow.student_group_id == StudentGroupRow.id
            )
        )

    async def create(
        self,
        *,
        school_id: str,
        user_id: str,
        name: str,
        reference_photo_path: str | None = None,
        reference_photo_thumbnail_path: str | None = None,
    ) -> Student:
        sid = req_uuid(school_id, field="school_id")
        uid = req_uuid(user_id, field="user_id")
        async with self._sessionmaker() as session, session.begin():
            row = StudentRow(
                school_id=sid,
                user_id=uid,
                name=name,
                reference_photo_path=reference_photo_path,
                reference_photo_thumbnail_path=reference_photo_thumbnail_path,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            # The login was created (in a prior transaction) before this call; fetch
            # its email so the returned read model carries it (decisions/0033). A fresh
            # student has no class yet, so group_name defaults to None.
            email = (
                await session.execute(select(UserRow.email).where(UserRow.id == uid))
            ).scalar_one()
            return _to_student(row, email)

    async def get(self, school_id: str, student_id: str) -> Student | None:
        sid = opt_uuid(school_id)
        pid = opt_uuid(student_id)
        if sid is None or pid is None:
            return None  # malformed id -> not found (tenant-safe)
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_email_and_class().where(
                    StudentRow.id == pid, StudentRow.school_id == sid
                )
            )
            row = result.one_or_none()
            return _to_student(row[0], row[1], row[2]) if row is not None else None

    async def get_by_user_id(self, school_id: str, user_id: str) -> Student | None:
        """The student profile linked to a login account (decisions/0028).

        Resolves a logged-in student user to their ``student_id`` for the ``/me`` gallery
        + own-only download. Tenant-scoped: a foreign school never resolves."""
        sid = opt_uuid(school_id)
        uid = opt_uuid(user_id)
        if sid is None or uid is None:
            return None
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_email_and_class().where(
                    StudentRow.user_id == uid, StudentRow.school_id == sid
                )
            )
            row = result.one_or_none()
            return _to_student(row[0], row[1], row[2]) if row is not None else None

    async def list_by_school(self, school_id: str) -> list[Student]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_email_and_class()
                .where(StudentRow.school_id == sid)
                .order_by(StudentRow.created_at, StudentRow.id)  # stable on ties
            )
            return [_to_student(r[0], r[1], r[2]) for r in result.all()]

    def _filtered(
        self,
        sid: uuid.UUID,
        q: str | None,
        status: EnrollmentStatus | None,
        student_group_id: str | None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[ColumnElement[bool]]:
        """The shared WHERE clauses for the paginated students reads (BP9 + BP11a class
        filter + BP11c focus scope). A malformed ``student_group_id`` yields no rows (never
        an ``IS NULL`` that would wrongly match un-classed students). ``scope_group_ids`` (a
        teacher's focus) limits to that set of classes — unlike events, an un-classed student
        is **not** included (they're no teacher's student); an empty scope yields no rows."""
        conds: list[ColumnElement[bool]] = [StudentRow.school_id == sid]
        if status is not None:
            conds.append(StudentRow.enrollment_status == status.value)
        if student_group_id is not None:
            gid = opt_uuid(student_group_id)
            conds.append(
                StudentRow.student_group_id == gid if gid is not None else false()
            )
        if scope_group_ids is not None:
            gids = [
                g for g in (opt_uuid(x) for x in scope_group_ids) if g is not None
            ]
            conds.append(
                StudentRow.student_group_id.in_(gids) if gids else false()
            )
        if q:
            term = ilike_term(q)
            conds.append(
                or_(
                    StudentRow.name.ilike(term, escape=LIKE_ESCAPE),
                    UserRow.email.ilike(term, escape=LIKE_ESCAPE),
                )
            )
        return conds

    async def list_page(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: StudentSort = StudentSort.NAME,
        descending: bool = False,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[Student]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        col = _SORT_COLS.get(sort, StudentRow.created_at)
        order = (
            (col.desc(), StudentRow.id.desc())
            if descending
            else (col.asc(), StudentRow.id.asc())
        )
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_email_and_class()
                .where(*self._filtered(sid, q, status, student_group_id, scope_group_ids))
                .order_by(*order)
                .offset(offset)
                .limit(limit)
            )
            return [_to_student(r[0], r[1], r[2]) for r in result.all()]

    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(StudentRow)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(*self._filtered(sid, q, status, student_group_id, scope_group_ids))
            )
            return int(result.scalar_one())

    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[str]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow.id)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(*self._filtered(sid, q, status, student_group_id, scope_group_ids))
            )
            return [str(r) for r in result.scalars().all()]

    async def list_by_ids(
        self, school_id: str, student_ids: Sequence[str]
    ) -> list[Student]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        ids = [pid for pid in (opt_uuid(s) for s in student_ids) if pid is not None]
        if not ids:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_email_and_class()
                .where(StudentRow.school_id == sid, StudentRow.id.in_(ids))
                .order_by(StudentRow.created_at, StudentRow.id)  # stable on ties
            )
            return [_to_student(r[0], r[1], r[2]) for r in result.all()]

    async def resolve_by_emails(
        self, school_id: str, emails: Sequence[str]
    ) -> list[Student]:
        """Students in this school whose login email matches one of ``emails``
        (case-insensitive) — BP10 bulk-photo filename→student matching. Tenant-scoped; order
        not guaranteed. The email set is bounded by the route's per-batch cap."""
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        lowered = [e.lower() for e in emails]
        if not lowered:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_email_and_class().where(
                    StudentRow.school_id == sid,
                    func.lower(UserRow.email).in_(lowered),
                )
            )
            return [_to_student(r[0], r[1], r[2]) for r in result.all()]

    async def enrollment_counts(self, school_id: str) -> dict[EnrollmentStatus, int]:
        """Students grouped by enrollment status for one school (BP1 dashboard).

        One grouped scan of the tenant's slice (``ix_students_school``); every status
        key is present (zero-filled) so callers never key-miss."""
        counts = {s: 0 for s in EnrollmentStatus}
        sid = opt_uuid(school_id)
        if sid is None:
            return counts
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow.enrollment_status, func.count())
                .where(StudentRow.school_id == sid)
                .group_by(StudentRow.enrollment_status)
            )
            for status_value, n in result.all():
                counts[EnrollmentStatus(status_value)] = n
        return counts

    async def counts_by_school(self) -> dict[str, int]:
        """Students per school across all schools (BP2 platform rollup).

        One grouped scan; cross-tenant on purpose (reachable only behind
        ``school:manage``). Keys are canonical UUID strings, matching the domain ids."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow.school_id, func.count()).group_by(
                    StudentRow.school_id
                )
            )
            return {str(school_id): n for school_id, n in result.all()}

    async def enrolled_counts_by_school(self) -> dict[str, int]:
        """Successfully-enrolled students per school across all schools (BP14 estate funnel).

        The ``enrollment_status = enrolled`` sibling of ``counts_by_school``: one grouped scan,
        cross-tenant (reachable only behind ``school:manage``). Keys are canonical UUID strings."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow.school_id, func.count())
                .where(
                    StudentRow.enrollment_status == EnrollmentStatus.ENROLLED.value
                )
                .group_by(StudentRow.school_id)
            )
            return {str(school_id): n for school_id, n in result.all()}

    async def set_enrollment(
        self,
        student_id: str,
        *,
        status: EnrollmentStatus,
        failure_reason: EnrollmentFailureReason | None = None,
    ) -> None:
        key = req_uuid(student_id, field="student_id")
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(StudentRow, key)
            if row is None:
                raise NotFoundError(f"student not found: {student_id}")
            # ORM mutation -> flush on commit; also trips updated_at's onupdate. The
            # reason is always overwritten (set on failure, cleared to None on success),
            # so it never lingers stale after a fixed re-enroll (BP7b).
            row.enrollment_status = status.value
            row.enrollment_failure_reason = (
                failure_reason.value if failure_reason is not None else None
            )

    async def set_reference_photo(
        self,
        student_id: str,
        *,
        reference_photo_path: str,
        reference_photo_thumbnail_path: str | None = None,
    ) -> None:
        key = req_uuid(student_id, field="student_id")
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(StudentRow, key)
            if row is None:
                raise NotFoundError(f"student not found: {student_id}")
            # ORM mutation -> flush on commit; also trips updated_at's onupdate (BP7d-2).
            # BP17: the display-only thumbnail is replaced in lockstep (may be None if the
            # backend couldn't generate one — the download then falls back to full-res).
            row.reference_photo_path = reference_photo_path
            row.reference_photo_thumbnail_path = reference_photo_thumbnail_path

    async def set_group(
        self, student_id: str, *, student_group_id: str | None
    ) -> None:
        """Assign (or clear, with ``None``) one student's class (BP11a). The service
        validates that a non-null ``student_group_id`` names a class in the same school
        first, so a malformed non-null id here is a programming error (raised)."""
        key = req_uuid(student_id, field="student_id")
        gid = (
            req_uuid(student_group_id, field="student_group_id")
            if student_group_id is not None
            else None
        )
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(StudentRow, key)
            if row is None:
                raise NotFoundError(f"student not found: {student_id}")
            row.student_group_id = gid  # ORM mutation -> trips updated_at's onupdate

    async def set_group_bulk(
        self,
        school_id: str,
        *,
        student_group_id: str,
        student_ids: Sequence[str],
    ) -> int:
        """Assign many of one school's students to a class in one UPDATE (BP11a). Tenant-
        scoped: only rows whose ``school_id`` matches are touched (a foreign id is silently
        skipped). Returns the count updated. The service validates the class first."""
        sid = opt_uuid(school_id)
        gid = opt_uuid(student_group_id)
        if sid is None or gid is None:
            return 0
        ids = [pid for pid in (opt_uuid(s) for s in student_ids) if pid is not None]
        if not ids:
            return 0
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                update(StudentRow)
                .where(StudentRow.school_id == sid, StudentRow.id.in_(ids))
                .values(student_group_id=gid)
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]
