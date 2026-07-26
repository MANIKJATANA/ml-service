"""Postgres implementation of :class:`EventCategoryRepository` (BP11b, decisions/0059).

Backend-owned, tenant-configurable event categories. Reads are tenant-scoped: every
``get``/``list``/``delete`` takes ``school_id`` so a category from another school is invisible.
Deleting a category un-tags its events via the ``events.category_id`` ``ON DELETE SET NULL`` FK —
never an event delete.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import EventCategory as EventCategoryRow
from backend.domain.models import EventCategory


def _to_category(row: EventCategoryRow) -> EventCategory:
    return EventCategory(
        id=str(row.id),
        school_id=str(row.school_id),
        name=row.name,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresEventCategoryRepository:
    """``EventCategoryRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, *, school_id: str, name: str) -> EventCategory:
        sid = req_uuid(school_id, field="school_id")
        async with self._sessionmaker() as session, session.begin():
            row = EventCategoryRow(school_id=sid, name=name)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_category(row)

    async def get(self, school_id: str, category_id: str) -> EventCategory | None:
        sid = opt_uuid(school_id)
        cid = opt_uuid(category_id)
        if sid is None or cid is None:
            return None
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(EventCategoryRow).where(
                        EventCategoryRow.id == cid,
                        EventCategoryRow.school_id == sid,
                    )
                )
            ).scalar_one_or_none()
            return _to_category(row) if row is not None else None

    async def get_by_name(
        self, school_id: str, name: str
    ) -> EventCategory | None:
        sid = opt_uuid(school_id)
        if sid is None:
            return None
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(EventCategoryRow).where(
                        EventCategoryRow.school_id == sid,
                        func.lower(EventCategoryRow.name) == name.strip().lower(),
                    )
                )
            ).scalar_one_or_none()
            return _to_category(row) if row is not None else None

    async def list_by_school(self, school_id: str) -> list[EventCategory]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventCategoryRow)
                .where(EventCategoryRow.school_id == sid)
                .order_by(EventCategoryRow.name, EventCategoryRow.id)  # stable on ties
            )
            return [_to_category(r) for r in result.scalars().all()]

    async def delete(self, school_id: str, category_id: str) -> bool:
        sid = opt_uuid(school_id)
        cid = opt_uuid(category_id)
        if sid is None or cid is None:
            return False
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(EventCategoryRow, cid)
            if row is None or row.school_id != sid:  # tenant-scoped
                return False
            await session.delete(row)  # events SET NULL via the FK
            return True

    async def seed_defaults(self, school_id: str, names: Sequence[str]) -> None:
        """Insert the given category names for a school, skipping any already present
        (idempotent — a fresh school has none). Names compared case-insensitively."""
        sid = opt_uuid(school_id)
        if sid is None:
            return
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                select(EventCategoryRow.name).where(EventCategoryRow.school_id == sid)
            )
            have = {n.lower() for n in result.scalars().all()}
            for name in names:
                if name.strip().lower() not in have:
                    session.add(EventCategoryRow(school_id=sid, name=name))
