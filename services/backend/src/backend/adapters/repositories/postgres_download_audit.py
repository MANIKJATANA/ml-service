"""Postgres implementation of :class:`DownloadAuditRepository` (BP8b, decisions/0050).

Append-only audit of entitled media downloads. ``record`` inserts one immutable row; the
reads are tenant-scoped, newest-first, and return pure ``DownloadAuditEntry`` value objects
the ``AuditService`` composes display data onto (never a SQL join across services). A row
whose actor/subject account was later deleted keeps the row (its FK is SET NULL), so those
ids read back as ``None``.
"""

from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import DownloadAudit as AuditRow
from backend.domain.models import DownloadAuditEntry


def _to_entry(row: AuditRow) -> DownloadAuditEntry:
    return DownloadAuditEntry(
        id=str(row.id),
        school_id=str(row.school_id),
        media_id=str(row.media_id),
        event_id=str(row.event_id),
        actor_user_id=str(row.actor_user_id) if row.actor_user_id is not None else None,
        actor_role=row.actor_role,
        subject_student_id=(
            str(row.subject_student_id)
            if row.subject_student_id is not None
            else None
        ),
        created_at=row.created_at,
    )


class PostgresDownloadAuditRepository:
    """``DownloadAuditRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(
        self,
        *,
        school_id: str,
        media_id: str,
        event_id: str,
        actor_user_id: str,
        actor_role: str,
        subject_student_id: str | None,
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        mid = req_uuid(media_id, field="media_id")
        eid = req_uuid(event_id, field="event_id")
        aid = req_uuid(actor_user_id, field="actor_user_id")
        subj = (
            req_uuid(subject_student_id, field="subject_student_id")
            if subject_student_id is not None
            else None
        )
        stmt = insert(AuditRow).values(
            school_id=sid,
            media_id=mid,
            event_id=eid,
            actor_user_id=aid,
            actor_role=actor_role,
            subject_student_id=subj,
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def list_for_media(
        self, school_id: str, media_id: str, *, limit: int
    ) -> list[DownloadAuditEntry]:
        sid = opt_uuid(school_id)
        mid = opt_uuid(media_id)
        if sid is None or mid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(AuditRow)
                .where(AuditRow.school_id == sid, AuditRow.media_id == mid)
                # id as a stable tiebreaker so same-instant rows never reorder across pages.
                .order_by(AuditRow.created_at.desc(), AuditRow.id.desc())
                .limit(limit)
            )
            return [_to_entry(r) for r in result.scalars().all()]

    async def count_for_media(self, school_id: str, media_id: str) -> int:
        sid = opt_uuid(school_id)
        mid = opt_uuid(media_id)
        if sid is None or mid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(AuditRow)
                .where(AuditRow.school_id == sid, AuditRow.media_id == mid)
            )
            return int(result.scalar_one())

    async def list_recent(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        event_id: str | None = None,
        student_id: str | None = None,
    ) -> list[DownloadAuditEntry]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        conds = [AuditRow.school_id == sid]
        if event_id is not None:
            eid = opt_uuid(event_id)
            if eid is None:
                return []
            conds.append(AuditRow.event_id == eid)
        if student_id is not None:
            stid = opt_uuid(student_id)
            if stid is None:
                return []
            conds.append(AuditRow.subject_student_id == stid)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(AuditRow)
                .where(*conds)
                # id as a stable tiebreaker so same-instant rows never reorder across pages.
                .order_by(AuditRow.created_at.desc(), AuditRow.id.desc())
                .offset(offset)
                .limit(limit)
            )
            return [_to_entry(r) for r in result.scalars().all()]

    async def count_recent(
        self,
        school_id: str,
        *,
        event_id: str | None = None,
        student_id: str | None = None,
    ) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        conds = [AuditRow.school_id == sid]
        if event_id is not None:
            eid = opt_uuid(event_id)
            if eid is None:
                return 0
            conds.append(AuditRow.event_id == eid)
        if student_id is not None:
            stid = opt_uuid(student_id)
            if stid is None:
                return 0
            conds.append(AuditRow.subject_student_id == stid)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count()).select_from(AuditRow).where(*conds)
            )
            return int(result.scalar_one())

    async def count_distinct_saver_students(self, school_id: str) -> int:
        """Distinct students who have saved >=1 of their OWN photos (BP23 "Saved a photo").

        Counts distinct ``subject_student_id`` — which is non-null ONLY on a student
        self-download (a staff bulk-download leaves it null), so staff downloads are correctly
        excluded. One DISTINCT scan (``ix_download_audit_student``), tenant-scoped."""
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count(func.distinct(AuditRow.subject_student_id))).where(
                    AuditRow.school_id == sid,
                    AuditRow.subject_student_id.is_not(None),
                )
            )
            return int(result.scalar_one())

    async def download_counts_by_student_for_event(
        self, school_id: str, event_id: str
    ) -> dict[str, int]:
        """Per-student self-download count for one event (BP23 roster "Downloaded" column).

        Groups the event's student self-downloads by ``subject_student_id`` (non-null only on a
        self-download). One grouped scan (``ix_download_audit_event``), tenant-scoped; keys are
        canonical UUID strings (only students with >=1 self-download appear — caller zero-fills)."""
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(AuditRow.subject_student_id, func.count())
                .where(
                    AuditRow.school_id == sid,
                    AuditRow.event_id == eid,
                    AuditRow.subject_student_id.is_not(None),
                )
                .group_by(AuditRow.subject_student_id)
            )
            return {str(student_id): n for student_id, n in result.all()}
