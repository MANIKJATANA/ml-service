"""Postgres implementation of :class:`WhatsAppSendLogRepository` (W2, migration 0023).

Append-only audit of WhatsApp send attempts. ``record`` inserts one immutable row (own
transaction, best-effort by the caller); ``count_sent_since`` counts ``sent`` rows since the
UTC month start (the monthly budget cap); ``list_for_student`` returns a student's recent
history newest-first. Rows outlive an erased student/media (their FKs are SET NULL), so those
ids read back as ``None``. The recipient phone number is NEVER stored (PII-free).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import WhatsAppSendLog as SendRow
from backend.domain.models import WhatsAppSendLogEntry


def _to_entry(row: SendRow) -> WhatsAppSendLogEntry:
    return WhatsAppSendLogEntry(
        id=str(row.id),
        school_id=str(row.school_id),
        student_id=str(row.student_id) if row.student_id is not None else None,
        media_id=str(row.media_id) if row.media_id is not None else None,
        actor_user_id=(
            str(row.actor_user_id) if row.actor_user_id is not None else None
        ),
        actor_role=row.actor_role,
        sender_number=row.sender_number,
        status=row.status,
        provider_message_id=row.provider_message_id,
        error=row.error,
        created_at=row.created_at,
    )


class PostgresWhatsAppSendLogRepository:
    """``WhatsAppSendLogRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(
        self,
        *,
        school_id: str,
        student_id: str | None,
        media_id: str | None,
        actor_user_id: str | None,
        actor_role: str,
        sender_number: str,
        status: str,
        provider_message_id: str | None,
        error: str | None,
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        stid = (
            req_uuid(student_id, field="student_id")
            if student_id is not None
            else None
        )
        mid = req_uuid(media_id, field="media_id") if media_id is not None else None
        aid = (
            req_uuid(actor_user_id, field="actor_user_id")
            if actor_user_id is not None
            else None
        )
        stmt = insert(SendRow).values(
            school_id=sid,
            student_id=stid,
            media_id=mid,
            actor_user_id=aid,
            actor_role=actor_role,
            sender_number=sender_number,
            status=status,
            provider_message_id=provider_message_id,
            error=error,
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def count_sent_since(self, school_id: str, *, since: datetime) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(SendRow)
                .where(
                    SendRow.school_id == sid,
                    SendRow.status == "sent",
                    SendRow.created_at >= since,
                )
            )
            return int(result.scalar_one())

    async def list_for_student(
        self, school_id: str, student_id: str, *, limit: int
    ) -> list[WhatsAppSendLogEntry]:
        sid = opt_uuid(school_id)
        stid = opt_uuid(student_id)
        if sid is None or stid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(SendRow)
                .where(SendRow.school_id == sid, SendRow.student_id == stid)
                # id as a stable tiebreaker so same-instant rows never reorder across pages.
                .order_by(SendRow.created_at.desc(), SendRow.id.desc())
                .limit(limit)
            )
            return [_to_entry(r) for r in result.scalars().all()]
