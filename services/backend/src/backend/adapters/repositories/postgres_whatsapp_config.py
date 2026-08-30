"""Postgres implementation of :class:`WhatsAppConfigRepository` (W1).

Backend-owned, per-school NON-SECRET WhatsApp config. One row per school keyed on
``school_id`` (PK), so reads are inherently tenant-scoped. ``upsert`` writes the row on first
save and updates it thereafter (``ON CONFLICT (school_id) DO UPDATE``), bumping ``updated_at``.
The one provider secret lives in settings — never in a column here.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import SchoolWhatsAppConfig as ConfigRow
from backend.domain.models import SchoolWhatsAppConfig


def _to_config(row: ConfigRow) -> SchoolWhatsAppConfig:
    return SchoolWhatsAppConfig(
        school_id=str(row.school_id),
        enabled=row.enabled,
        sender_number=row.sender_number,
        template_name=row.template_name,
        business_name=row.business_name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresWhatsAppConfigRepository:
    """``WhatsAppConfigRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self, school_id: str) -> SchoolWhatsAppConfig | None:
        sid = opt_uuid(school_id)
        if sid is None:
            return None
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(ConfigRow).where(ConfigRow.school_id == sid)
                )
            ).scalar_one_or_none()
            return _to_config(row) if row is not None else None

    async def upsert(
        self,
        *,
        school_id: str,
        enabled: bool,
        sender_number: str | None,
        template_name: str | None,
        business_name: str | None,
    ) -> SchoolWhatsAppConfig:
        sid = req_uuid(school_id, field="school_id")
        stmt = (
            postgresql.insert(ConfigRow)
            .values(
                school_id=sid,
                enabled=enabled,
                sender_number=sender_number,
                template_name=template_name,
                business_name=business_name,
            )
            .on_conflict_do_update(
                index_elements=["school_id"],
                set_={
                    "enabled": enabled,
                    "sender_number": sender_number,
                    "template_name": template_name,
                    "business_name": business_name,
                    "updated_at": func.now(),
                },
            )
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)
        # Re-select so the returned row carries the server-side timestamps.
        row = await self.get(school_id)
        assert row is not None  # just upserted
        return row
