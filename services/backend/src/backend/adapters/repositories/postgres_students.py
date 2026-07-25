"""Postgres implementation of :class:`StudentRepository` (decisions/0026).

Reads are tenant-scoped: every ``get``/``list`` takes ``school_id`` so a student
that belongs to another school is invisible (returned as ``None``/absent), enforcing
tenant isolation at the query layer (decisions/0022). Each read JOINs ``users`` to
carry the student's login ``email`` on the read model (decisions/0033).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import (
    LIKE_ESCAPE,
    ilike_term,
    opt_uuid,
    req_uuid,
)
from backend.db.models import Student as StudentRow
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


def _to_student(row: StudentRow, email: str) -> Student:
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
    )


class PostgresStudentRepository:
    """``StudentRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

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
            # its email so the returned read model carries it (decisions/0033).
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
                select(StudentRow, UserRow.email)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(StudentRow.id == pid, StudentRow.school_id == sid)
            )
            pair = result.one_or_none()
            return _to_student(pair[0], pair[1]) if pair is not None else None

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
                select(StudentRow, UserRow.email)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(StudentRow.user_id == uid, StudentRow.school_id == sid)
            )
            pair = result.one_or_none()
            return _to_student(pair[0], pair[1]) if pair is not None else None

    async def list_by_school(self, school_id: str) -> list[Student]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow, UserRow.email)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(StudentRow.school_id == sid)
                .order_by(StudentRow.created_at, StudentRow.id)  # stable on ties
            )
            return [_to_student(r[0], r[1]) for r in result.all()]

    def _filtered(
        self, sid: uuid.UUID, q: str | None, status: EnrollmentStatus | None
    ) -> list[ColumnElement[bool]]:
        """The shared WHERE clauses for the paginated students reads (BP9)."""
        conds: list[ColumnElement[bool]] = [StudentRow.school_id == sid]
        if status is not None:
            conds.append(StudentRow.enrollment_status == status.value)
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
                select(StudentRow, UserRow.email)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(*self._filtered(sid, q, status))
                .order_by(*order)
                .offset(offset)
                .limit(limit)
            )
            return [_to_student(r[0], r[1]) for r in result.all()]

    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
    ) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(StudentRow)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(*self._filtered(sid, q, status))
            )
            return int(result.scalar_one())

    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EnrollmentStatus | None = None,
    ) -> list[str]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow.id)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(*self._filtered(sid, q, status))
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
                select(StudentRow, UserRow.email)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(StudentRow.school_id == sid, StudentRow.id.in_(ids))
                .order_by(StudentRow.created_at, StudentRow.id)  # stable on ties
            )
            return [_to_student(r[0], r[1]) for r in result.all()]

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
                select(StudentRow, UserRow.email)
                .join(UserRow, StudentRow.user_id == UserRow.id)
                .where(
                    StudentRow.school_id == sid,
                    func.lower(UserRow.email).in_(lowered),
                )
            )
            return [_to_student(r[0], r[1]) for r in result.all()]

    async def enrollment_counts(
        self, school_id: str
    ) -> dict[EnrollmentStatus, int]:
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
