"""Postgres implementation of :class:`MatchCorrectionRepository` (BP5, decisions/0042).

Backend-owned corrections over the ML ``matches``, keyed on the ``(media_id, student_id)``
pair. ``upsert`` writes latest-verdict-wins on that natural key; the reads are tenant-scoped
and return pure ``MatchCorrection`` value objects the ``GalleryService``/``ReviewService``
overlay onto the ML appearances (never a SQL join to the ``matches`` seam).
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import MatchCorrection as CorrectionRow
from backend.domain.models import MatchCorrection, MatchVerdict


def _to_correction(row: CorrectionRow) -> MatchCorrection:
    return MatchCorrection(
        media_id=str(row.media_id),
        student_id=str(row.student_id),
        event_id=str(row.event_id),
        verdict=MatchVerdict(row.verdict),
        resolves_review=row.resolves_review,
    )


class PostgresMatchCorrectionRepository:
    """``MatchCorrectionRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def upsert(
        self,
        *,
        school_id: str,
        media_id: str,
        student_id: str,
        event_id: str,
        verdict: MatchVerdict,
        corrected_by: str | None,
        reason: str | None,
        resolves_review: bool,
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        mid = req_uuid(media_id, field="media_id")
        stid = req_uuid(student_id, field="student_id")
        eid = req_uuid(event_id, field="event_id")
        cby = (
            req_uuid(corrected_by, field="corrected_by")
            if corrected_by is not None
            else None
        )
        stmt = (
            insert(CorrectionRow)
            .values(
                school_id=sid,
                media_id=mid,
                student_id=stid,
                event_id=eid,
                verdict=verdict.value,
                corrected_by=cby,
                reason=reason,
                resolves_review=resolves_review,
            )
            .on_conflict_do_update(
                constraint="uq_match_corrections_pair",
                set_={
                    "verdict": verdict.value,
                    "corrected_by": cby,
                    "reason": reason,
                    "resolves_review": resolves_review,
                    "updated_at": func.now(),
                },
            )
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def get(
        self, school_id: str, media_id: str, student_id: str
    ) -> MatchCorrection | None:
        sid = opt_uuid(school_id)
        mid = opt_uuid(media_id)
        stid = opt_uuid(student_id)
        if sid is None or mid is None or stid is None:
            return None
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(CorrectionRow).where(
                    CorrectionRow.school_id == sid,
                    CorrectionRow.media_id == mid,
                    CorrectionRow.student_id == stid,
                )
            )
            row = result.scalar_one_or_none()
            return _to_correction(row) if row is not None else None

    async def delete(self, school_id: str, media_id: str, student_id: str) -> None:
        sid = opt_uuid(school_id)
        mid = opt_uuid(media_id)
        stid = opt_uuid(student_id)
        if sid is None or mid is None or stid is None:
            return
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                delete(CorrectionRow).where(
                    CorrectionRow.school_id == sid,
                    CorrectionRow.media_id == mid,
                    CorrectionRow.student_id == stid,
                )
            )

    async def list_for_media(
        self, school_id: str, media_id: str
    ) -> list[MatchCorrection]:
        sid = opt_uuid(school_id)
        mid = opt_uuid(media_id)
        if sid is None or mid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(CorrectionRow).where(
                    CorrectionRow.school_id == sid, CorrectionRow.media_id == mid
                )
            )
            return [_to_correction(r) for r in result.scalars().all()]

    async def list_for_event(
        self, school_id: str, event_id: str
    ) -> list[MatchCorrection]:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(CorrectionRow).where(
                    CorrectionRow.school_id == sid, CorrectionRow.event_id == eid
                )
            )
            return [_to_correction(r) for r in result.scalars().all()]

    async def list_for_student(
        self, school_id: str, student_id: str
    ) -> list[MatchCorrection]:
        sid = opt_uuid(school_id)
        stid = opt_uuid(student_id)
        if sid is None or stid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(CorrectionRow).where(
                    CorrectionRow.school_id == sid, CorrectionRow.student_id == stid
                )
            )
            return [_to_correction(r) for r in result.scalars().all()]

    async def count_resolved(self, school_id: str) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(CorrectionRow)
                .where(
                    CorrectionRow.school_id == sid,
                    CorrectionRow.resolves_review.is_(True),
                )
            )
            return int(result.scalar_one())
