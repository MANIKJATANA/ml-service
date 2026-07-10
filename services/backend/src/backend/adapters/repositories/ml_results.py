"""Postgres ``MlResultsReader`` over the ML-owned ``matches`` table (decisions/0028).

Read-only. Every method is tenant-scoped by ``school_id`` and returns pure
``Appearance`` value objects (join keys + the two decision facts); the ``GalleryService``
joins those against backend-owned rows for all display data. The ``matches`` join keys
are strings on the ML side (canonical UUID strings — decisions/0022), so they compare
directly against the backend's string ids — no UUID parsing here.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.db.ml_read import matches
from backend.domain.models import Appearance

# Exactly the columns db/ml_read.py declares as consumed (guarded by the Phase-7
# information_schema contract test).
_COLUMNS = (
    matches.c.student_id,
    matches.c.media_id,
    matches.c.event_id,
    matches.c.confidence_score,
    matches.c.needs_review,
)


def _to_appearance(row: Row[Any]) -> Appearance:
    return Appearance(
        student_id=row.student_id,
        media_id=row.media_id,
        event_id=row.event_id,
        confidence=row.confidence_score,
        needs_review=row.needs_review,
    )


class PostgresMlResultsReader:
    """``MlResultsReader`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_event_appearances(
        self, school_id: str, event_id: str
    ) -> list[Appearance]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(*_COLUMNS)
                .where(
                    matches.c.school_id == school_id,
                    matches.c.event_id == event_id,
                )
                .order_by(matches.c.student_id, matches.c.media_id)
            )
            return [_to_appearance(r) for r in result.all()]

    async def list_student_appearances(
        self, school_id: str, student_id: str
    ) -> list[Appearance]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(*_COLUMNS)
                .where(
                    matches.c.school_id == school_id,
                    matches.c.student_id == student_id,
                )
                .order_by(matches.c.event_id, matches.c.media_id)
            )
            return [_to_appearance(r) for r in result.all()]

    async def list_media_appearances(
        self, school_id: str, media_id: str
    ) -> list[Appearance]:
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(*_COLUMNS)
                .where(
                    matches.c.school_id == school_id,
                    matches.c.media_id == media_id,
                )
                .order_by(matches.c.student_id)
            )
            return [_to_appearance(r) for r in result.all()]
