"""Postgres implementation of :class:`NotificationReadRepository` (BP4, decisions/0041).

Per-(student, event) 'seen' state for the derived in-app new-photos signal. Tenant-scoped
(every read takes ``school_id``). ``mark_seen`` upserts on the ``(student_id, event_id)``
natural key so opening an event's photos repeatedly just moves ``seen_at`` forward.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import NotificationRead as ReadRow


class PostgresNotificationReadRepository:
    """``NotificationReadRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def mark_seen(
        self, *, school_id: str, student_id: str, event_id: str
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        stid = req_uuid(student_id, field="student_id")
        eid = req_uuid(event_id, field="event_id")
        stmt = (
            insert(ReadRow)
            .values(school_id=sid, student_id=stid, event_id=eid)
            .on_conflict_do_update(
                constraint="uq_notification_reads_pair",
                set_={"seen_at": func.now(), "updated_at": func.now()},
            )
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def list_for_student(
        self, school_id: str, student_id: str
    ) -> dict[str, datetime]:
        sid = opt_uuid(school_id)
        stid = opt_uuid(student_id)
        if sid is None or stid is None:
            return {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(ReadRow.event_id, ReadRow.seen_at).where(
                    ReadRow.school_id == sid, ReadRow.student_id == stid
                )
            )
            return {str(event_id): seen_at for event_id, seen_at in result.all()}

    async def list_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, datetime]:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(ReadRow.student_id, ReadRow.seen_at).where(
                    ReadRow.school_id == sid, ReadRow.event_id == eid
                )
            )
            return {str(student_id): seen_at for student_id, seen_at in result.all()}
