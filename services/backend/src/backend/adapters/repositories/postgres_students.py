"""Postgres implementation of :class:`StudentRepository` (decisions/0026).

Reads are tenant-scoped: every ``get``/``list`` takes ``school_id`` so a student
that belongs to another school is invisible (returned as ``None``/absent), enforcing
tenant isolation at the query layer (decisions/0022). Each read JOINs ``users`` to
carry the student's login ``email`` on the read model (decisions/0033).
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import Student as StudentRow
from backend.db.models import User as UserRow
from backend.domain.errors import NotFoundError
from backend.domain.models import EnrollmentStatus, Student


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
        reference_photo_path: str,
    ) -> Student:
        sid = req_uuid(school_id, field="school_id")
        uid = req_uuid(user_id, field="user_id")
        async with self._sessionmaker() as session, session.begin():
            row = StudentRow(
                school_id=sid,
                user_id=uid,
                name=name,
                reference_photo_path=reference_photo_path,
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

    async def set_enrollment(
        self, student_id: str, *, status: EnrollmentStatus
    ) -> None:
        key = req_uuid(student_id, field="student_id")
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(StudentRow, key)
            if row is None:
                raise NotFoundError(f"student not found: {student_id}")
            # ORM mutation -> flush on commit; also trips updated_at's onupdate.
            row.enrollment_status = status.value
