"""Postgres implementation of :class:`SchoolRepository` (decisions/0023)."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import (
    LIKE_ESCAPE,
    ilike_term,
    opt_uuid,
)
from backend.db.models import School as SchoolRow
from backend.domain.models import School, SchoolSort, SchoolStatus

# Row-native sort columns (BP9); rollup count sorts (students/events/teachers/admins) take
# the id-scan path in the service, so a stray one falls back to ``name``.
_SORT_COLS = {
    SchoolSort.NAME: SchoolRow.name,
    SchoolSort.CREATED_AT: SchoolRow.created_at,
}


def _filtered(q: str | None) -> list[ColumnElement[bool]]:
    """The shared WHERE clause for the paginated platform schools reads (BP9)."""
    return [SchoolRow.name.ilike(ilike_term(q), escape=LIKE_ESCAPE)] if q else []


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

    async def list_page(
        self,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: SchoolSort = SchoolSort.NAME,
        descending: bool = False,
    ) -> list[School]:
        col = _SORT_COLS.get(sort, SchoolRow.name)
        order = (
            (col.desc(), SchoolRow.id.desc())
            if descending
            else (col.asc(), SchoolRow.id.asc())
        )
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(SchoolRow)
                .where(*_filtered(q))
                .order_by(*order)
                .offset(offset)
                .limit(limit)
            )
            return [_to_school(r) for r in result.scalars().all()]

    async def count_page(self, *, q: str | None = None) -> int:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count()).select_from(SchoolRow).where(*_filtered(q))
            )
            return int(result.scalar_one())

    async def list_ids(self, *, q: str | None = None) -> list[str]:
        async with self._sessionmaker() as session:
            result = await session.execute(select(SchoolRow.id).where(*_filtered(q)))
            return [str(r) for r in result.scalars().all()]

    async def list_by_ids(self, school_ids: Sequence[str]) -> list[School]:
        ids = [sid for sid in (opt_uuid(s) for s in school_ids) if sid is not None]
        if not ids:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(SchoolRow).where(SchoolRow.id.in_(ids))
            )
            return [_to_school(r) for r in result.scalars().all()]
