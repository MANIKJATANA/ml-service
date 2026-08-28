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

    async def count_distinct_seen_students(self, school_id: str) -> int:
        """Distinct students who have opened >=1 distribution (BP14 engagement rate).

        One scan of the tenant's ``notification_reads`` slice; a student with any 'seen' row
        counts once. Tenant-scoped."""
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count(func.distinct(ReadRow.student_id))).where(
                    ReadRow.school_id == sid
                )
            )
            return int(result.scalar_one())

    async def distinct_opened_event_ids(self, school_id: str) -> list[str]:
        """The distinct event ids that have >=1 student open (BP23 event-reach).

        The service intersects these with the currently-*announced* event ids (in-Python) so
        reach is honestly "of the announced events, how many were opened" — a never-inflated
        floor that can't over-report an event opened then un-announced. Seam-free (only
        ``notification_reads``); the audience-weighted "what share of each event's roster
        opened" would need the ML seam roster — deliberately out of scope. One DISTINCT scan,
        tenant-scoped."""
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(ReadRow.event_id)
                .where(ReadRow.school_id == sid)
                .distinct()
            )
            return [str(eid) for eid in result.scalars().all()]

    async def monthly_first_open_counts(self, school_id: str) -> dict[str, int]:
        """First-opens per calendar month for a school (BP23 engagement trend), keyed
        ``'YYYY-MM'``.

        Buckets on the row's immutable ``created_at`` — the TRUE first-ever open of that
        (student, event), which survives a re-announce (unlike ``seen_at``, which moves
        forward). Mirrors ``monthly_upload_counts``' shape; one grouped scan, tenant-scoped.
        A month can genuinely fall vs the prior — the point of a decline-capable line."""
        sid = opt_uuid(school_id)
        if sid is None:
            return {}
        month = func.to_char(func.date_trunc("month", ReadRow.created_at), "YYYY-MM")
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(month, func.count())
                .where(ReadRow.school_id == sid)
                .group_by(month)
            )
            return {str(m): n for m, n in result.all()}

    async def first_seen_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, datetime]:
        """Per-student FIRST-open time for one event (BP23 roster "ever opened").

        The immutable ``created_at`` keyed by student — the persistent first-open, distinct
        from ``list_for_event``'s ``seen_at`` (which resets on re-announce). Tenant-scoped."""
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(ReadRow.student_id, ReadRow.created_at).where(
                    ReadRow.school_id == sid, ReadRow.event_id == eid
                )
            )
            return {str(student_id): created for student_id, created in result.all()}
