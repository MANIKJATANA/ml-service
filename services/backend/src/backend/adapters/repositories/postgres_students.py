"""Postgres implementation of :class:`StudentRepository` (decisions/0026).

Reads are tenant-scoped: every ``get``/``list`` takes ``school_id`` so a student
that belongs to another school is invisible (returned as ``None``/absent), enforcing
tenant isolation at the query layer (decisions/0022).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import Student as StudentRow
from backend.domain.errors import NotFoundError
from backend.domain.models import EnrollmentStatus, Student


def _to_student(row: StudentRow) -> Student:
    return Student(
        id=str(row.id),
        school_id=str(row.school_id),
        user_id=str(row.user_id),
        name=row.name,
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
            return _to_student(row)

    async def get(self, school_id: str, student_id: str) -> Student | None:
        sid = opt_uuid(school_id)
        pid = opt_uuid(student_id)
        if sid is None or pid is None:
            return None  # malformed id -> not found (tenant-safe)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow).where(
                    StudentRow.id == pid, StudentRow.school_id == sid
                )
            )
            row = result.scalar_one_or_none()
            return _to_student(row) if row is not None else None

    async def get_by_user_id(
        self, school_id: str, user_id: str
    ) -> Student | None:
        """The student profile linked to a login account (decisions/0028).

        Resolves a logged-in student user to their ``student_id`` for the ``/me`` gallery
        + own-only download. Tenant-scoped: a foreign school never resolves."""
        sid = opt_uuid(school_id)
        uid = opt_uuid(user_id)
        if sid is None or uid is None:
            return None
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow).where(
                    StudentRow.user_id == uid, StudentRow.school_id == sid
                )
            )
            row = result.scalar_one_or_none()
            return _to_student(row) if row is not None else None

    async def list_by_school(self, school_id: str) -> list[Student]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow)
                .where(StudentRow.school_id == sid)
                .order_by(StudentRow.created_at, StudentRow.id)  # stable on ties
            )
            return [_to_student(r) for r in result.scalars().all()]

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
