"""Postgres implementation of :class:`SchoolRepository` (decisions/0023)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid
from backend.db.models import School as SchoolRow
from backend.domain.models import School, SchoolStatus


def _to_school(row: SchoolRow) -> School:
    return School(
        id=str(row.id),
        name=row.name,
        max_teachers=row.max_teachers,
        status=SchoolStatus(row.status),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresSchoolRepository:
    """``SchoolRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(self, *, name: str, max_teachers: int) -> School:
        async with self._sessionmaker() as session, session.begin():
            row = SchoolRow(name=name, max_teachers=max_teachers)
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_school(row)

    async def get(self, school_id: str) -> School | None:
        key = opt_uuid(school_id)
        if key is None:
            return None
        async with self._sessionmaker() as session:
            row = await session.get(SchoolRow, key)
            return _to_school(row) if row is not None else None

    async def list_all(self) -> list[School]:
        async with self._sessionmaker() as session:
            # (created_at, id) for a stable order when timestamps tie.
            result = await session.execute(
                select(SchoolRow).order_by(SchoolRow.created_at, SchoolRow.id)
            )
            return [_to_school(r) for r in result.scalars().all()]
