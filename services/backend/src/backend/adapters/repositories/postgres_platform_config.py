"""Postgres implementation of :class:`PlatformConfigRepository` (W-live-test, migration 0024).

Backend-owned platform-wide config SINGLETON: exactly one row keyed on the constant id
``"platform"``. ``get`` returns the row (or None before any save); ``upsert`` is a PARTIAL update
— it fetches the current row, applies only the provided (non-None) fields, and writes the merged
values via ``ON CONFLICT (id) DO UPDATE`` (bumping ``updated_at``). So a caller can save just the
token OR just the interim number/mode without clobbering the rest.

The ``meta_access_token`` column is a secret stored here per owner decision — this adapter reads
and writes it, but the API layer never returns it in full and it is NEVER logged.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.models import PlatformConfig as ConfigRow
from backend.domain.models import PlatformConfig

# The one row's primary key — the application never uses any other id.
_SINGLETON_ID = "platform"


def _to_config(row: ConfigRow) -> PlatformConfig:
    return PlatformConfig(
        id=row.id,
        meta_access_token=row.meta_access_token,
        interim_test_number=row.interim_test_number,
        interim_mode=row.interim_mode,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresPlatformConfigRepository:
    """``PlatformConfigRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def get(self) -> PlatformConfig | None:
        async with self._sessionmaker() as session:
            row = (
                await session.execute(
                    select(ConfigRow).where(ConfigRow.id == _SINGLETON_ID)
                )
            ).scalar_one_or_none()
            return _to_config(row) if row is not None else None

    async def upsert(
        self,
        *,
        meta_access_token: str | None,
        interim_test_number: str | None,
        interim_mode: bool | None,
    ) -> PlatformConfig:
        # Fetch-merge partial update: keep any field the caller didn't provide.
        current = await self.get()
        merged_token = (
            meta_access_token
            if meta_access_token is not None
            else (current.meta_access_token if current else None)
        )
        merged_number = (
            interim_test_number
            if interim_test_number is not None
            else (current.interim_test_number if current else None)
        )
        merged_mode = (
            interim_mode
            if interim_mode is not None
            else (current.interim_mode if current else False)
        )
        stmt = (
            postgresql.insert(ConfigRow)
            .values(
                id=_SINGLETON_ID,
                meta_access_token=merged_token,
                interim_test_number=merged_number,
                interim_mode=merged_mode,
            )
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "meta_access_token": merged_token,
                    "interim_test_number": merged_number,
                    "interim_mode": merged_mode,
                    "updated_at": func.now(),
                },
            )
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)
        row = await self.get()
        assert row is not None  # just upserted
        return row
