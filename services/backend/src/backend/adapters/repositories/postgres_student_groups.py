"""Postgres implementation of :class:`StudentGroupRepository` (BP11a, decisions/0058).

Backend-owned classes/sections. Reads are tenant-scoped: every ``get``/``list``/``update``/
``delete`` takes ``school_id`` so a class that belongs to another school is invisible
(returned as ``None``/``False``), enforcing tenant isolation at the query layer. Deleting a
class un-assigns its students via the ``students.student_group_id`` ``ON DELETE SET NULL``
FK — never a student delete.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import Student as StudentRow
from backend.db.models import StudentGroup as StudentGroupRow
from backend.domain.models import StudentGroup


def _to_group(row: StudentGroupRow) -> StudentGroup:
    return StudentGroup(
        id=str(row.id),
        school_id=str(row.school_id),
        name=row.name,
        grade=row.grade,
        section=row.section,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresStudentGroupRepository:
    """``StudentGroupRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self, *, school_id: str, name: str, grade: str | None, section: str | None
    ) -> StudentGroup:
        sid = req_uuid(school_id, field="school_id")
        async with self._sessionmaker() as session, session.begin():
            row = StudentGroupRow(
                school_id=sid, name=name, grade=grade, section=section
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_group(row)

    async def get(self, school_id: str, group_id: str) -> StudentGroup | None:
        sid = opt_uuid(school_id)
        gid = opt_uuid(group_id)
        if sid is None or gid is None:
            return None
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(StudentGroupRow).where(
                        StudentGroupRow.id == gid, StudentGroupRow.school_id == sid
                    )
                )
            ).scalar_one_or_none()
            return _to_group(row) if row is not None else None

    async def list_by_school(self, school_id: str) -> list[StudentGroup]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentGroupRow)
                .where(StudentGroupRow.school_id == sid)
                .order_by(StudentGroupRow.name, StudentGroupRow.id)  # stable on ties
            )
            return [_to_group(r) for r in result.scalars().all()]

    async def update(
        self,
        school_id: str,
        group_id: str,
        *,
        name: str,
        grade: str | None,
        section: str | None,
    ) -> StudentGroup | None:
        sid = opt_uuid(school_id)
        gid = opt_uuid(group_id)
        if sid is None or gid is None:
            return None
        async with self._sessionmaker() as session, session.begin():
            row = (
                await session.execute(
                    select(StudentGroupRow).where(
                        StudentGroupRow.id == gid, StudentGroupRow.school_id == sid
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            # ORM mutation -> flush on commit; also trips updated_at's onupdate.
            row.name = name
            row.grade = grade
            row.section = section
            await session.flush()
            await session.refresh(row)
            return _to_group(row)

    async def delete(self, school_id: str, group_id: str) -> bool:
        sid = opt_uuid(school_id)
        gid = opt_uuid(group_id)
        if sid is None or gid is None:
            return False
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(StudentGroupRow, gid)
            if row is None or row.school_id != sid:  # tenant-scoped
                return False
            await session.delete(row)  # students SET NULL via the FK
            return True

    async def student_counts(self, school_id: str) -> dict[str, int]:
        """Per-class member count for one school. One grouped scan over
        ``students.student_group_id`` (``ix_students_school_group``); classes with zero
        members are absent so the caller zero-fills."""
        sid = opt_uuid(school_id)
        if sid is None:
            return {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(StudentRow.student_group_id, func.count())
                .where(
                    StudentRow.school_id == sid,
                    StudentRow.student_group_id.is_not(None),
                )
                .group_by(StudentRow.student_group_id)
            )
            return {str(gid): n for gid, n in result.all()}
