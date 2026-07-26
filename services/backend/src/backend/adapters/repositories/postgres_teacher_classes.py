"""Postgres implementation of :class:`TeacherClassRepository` (BP11c, decisions/0060).

Backend-owned teacher ↔ class delegation links. Reads/writes are tenant-scoped: every method
takes ``school_id`` so a link in another school is invisible, enforcing tenant isolation at
the query layer (decisions/0022). The service validates the teacher + class are in-school
before ``add``/``replace_for_teacher``; the adapter still scopes every statement by
``school_id`` as the second line of defence. ``add`` is idempotent (``ON CONFLICT DO NOTHING``
on the ``(teacher_user_id, student_group_id)`` unique).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import TeacherClass as TeacherClassRow


class PostgresTeacherClassRepository:
    """``TeacherClassRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def add(
        self, *, school_id: str, teacher_user_id: str, student_group_id: str
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        tid = req_uuid(teacher_user_id, field="teacher_user_id")
        gid = req_uuid(student_group_id, field="student_group_id")
        async with self._sessionmaker() as session, session.begin():
            # Idempotent: a re-assign of the same (teacher, class) is a no-op, never a 500.
            await session.execute(
                pg_insert(TeacherClassRow)
                .values(
                    school_id=sid, teacher_user_id=tid, student_group_id=gid
                )
                .on_conflict_do_nothing(
                    index_elements=["teacher_user_id", "student_group_id"]
                )
            )

    async def remove(
        self, *, school_id: str, teacher_user_id: str, student_group_id: str
    ) -> bool:
        sid = opt_uuid(school_id)
        tid = opt_uuid(teacher_user_id)
        gid = opt_uuid(student_group_id)
        if sid is None or tid is None or gid is None:
            return False
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                delete(TeacherClassRow).where(
                    TeacherClassRow.school_id == sid,
                    TeacherClassRow.teacher_user_id == tid,
                    TeacherClassRow.student_group_id == gid,
                )
            )
            return bool(result.rowcount)  # type: ignore[attr-defined]

    async def replace_for_teacher(
        self,
        *,
        school_id: str,
        teacher_user_id: str,
        student_group_ids: Sequence[str],
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        tid = req_uuid(teacher_user_id, field="teacher_user_id")
        gids = [
            gid for gid in (opt_uuid(g) for g in student_group_ids) if gid is not None
        ]
        async with self._sessionmaker() as session, session.begin():
            # Clear the teacher's existing links in this school, then insert the new set —
            # both in one transaction so the "set" semantics are atomic.
            await session.execute(
                delete(TeacherClassRow).where(
                    TeacherClassRow.school_id == sid,
                    TeacherClassRow.teacher_user_id == tid,
                )
            )
            if gids:
                await session.execute(
                    pg_insert(TeacherClassRow)
                    .values(
                        [
                            {
                                "school_id": sid,
                                "teacher_user_id": tid,
                                "student_group_id": gid,
                            }
                            for gid in _dedupe(gids)
                        ]
                    )
                    .on_conflict_do_nothing(
                        index_elements=["teacher_user_id", "student_group_id"]
                    )
                )

    async def list_group_ids_for_teacher(
        self, school_id: str, teacher_user_id: str
    ) -> list[str]:
        sid = opt_uuid(school_id)
        tid = opt_uuid(teacher_user_id)
        if sid is None or tid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(TeacherClassRow.student_group_id).where(
                    TeacherClassRow.school_id == sid,
                    TeacherClassRow.teacher_user_id == tid,
                )
            )
            return [str(g) for g in result.scalars().all()]

    async def list_teacher_ids_for_group(
        self, school_id: str, student_group_id: str
    ) -> list[str]:
        sid = opt_uuid(school_id)
        gid = opt_uuid(student_group_id)
        if sid is None or gid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(TeacherClassRow.teacher_user_id).where(
                    TeacherClassRow.school_id == sid,
                    TeacherClassRow.student_group_id == gid,
                )
            )
            return [str(t) for t in result.scalars().all()]


def _dedupe(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Drop duplicate class ids (a repeated id in one PUT would trip the batch insert)."""
    seen: set[uuid.UUID] = set()
    out: list[uuid.UUID] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out
