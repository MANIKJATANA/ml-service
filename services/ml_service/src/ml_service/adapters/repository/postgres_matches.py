"""Postgres ``MatchRepository`` (SQLAlchemy 2.x async) — the default match sink.

``save_batch`` is the only write path (architecture §3.4) and uses
``INSERT ... ON CONFLICT (media_id, student_id) DO UPDATE`` where a **higher**
confidence wins (architecture §8.2) — the DB-side second layer of idempotency
(NFR-5) behind the worker's in-memory dedupe.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ml_service.db.models import Match
from ml_service.domain.models import FaceBox, MatchRecord


def _bbox_json(bbox: FaceBox | None) -> dict[str, float] | None:
    if bbox is None:
        return None
    return {
        "x1": bbox.x1,
        "y1": bbox.y1,
        "x2": bbox.x2,
        "y2": bbox.y2,
        "score": bbox.score,
    }


class PostgresMatchRepository:
    """Persists match records to Postgres."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def save_batch(self, records: list[MatchRecord]) -> None:
        if not records:
            return
        values = [self._to_row(r) for r in records]
        stmt = pg_insert(Match).values(values)
        stmt = stmt.on_conflict_do_update(
            index_elements=["media_id", "student_id"],
            set_={
                "event_id": stmt.excluded.event_id,
                "media_type": stmt.excluded.media_type,
                "confidence_score": stmt.excluded.confidence_score,
                "bbox": stmt.excluded.bbox,
                "frame_timestamp_ms": stmt.excluded.frame_timestamp_ms,
                "needs_review": stmt.excluded.needs_review,
                "embedding_model_version": stmt.excluded.embedding_model_version,
                "detector_model_version": stmt.excluded.detector_model_version,
                "threshold_used": stmt.excluded.threshold_used,
                "gap_threshold_used": stmt.excluded.gap_threshold_used,
                "frames_matched": stmt.excluded.frames_matched,
            },
            # Only overwrite when reprocessing found a higher-confidence match.
            where=stmt.excluded.confidence_score > Match.confidence_score,
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def exists(self, media_id: str, student_id: str) -> bool:
        stmt = (
            select(Match.match_id)
            .where(Match.media_id == media_id, Match.student_id == student_id)
            .limit(1)
        )
        async with self._sessionmaker() as session:
            result = await session.execute(stmt)
            return result.first() is not None

    async def delete_by_student(self, school_id: str, student_id: str) -> None:
        """Purge every match for one student (BP8e erasure) — tenant-scoped."""
        stmt = delete(Match).where(
            Match.school_id == school_id, Match.student_id == student_id
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    def _to_row(self, r: MatchRecord) -> dict[str, object]:
        return {
            "match_id": uuid.uuid4(),
            "school_id": r.school_id,
            "event_id": r.event_id,
            "student_id": r.student_id,
            "media_id": r.media_id,
            "media_type": r.media_type.value,
            "confidence_score": r.confidence_score,
            "bbox": _bbox_json(r.bbox),
            "frame_timestamp_ms": r.frame_timestamp_ms,
            "needs_review": r.needs_review,
            "embedding_model_version": r.embedding_model_version,
            "detector_model_version": r.detector_model_version,
            "threshold_used": r.threshold_used,
            "gap_threshold_used": r.gap_threshold_used,
            "frames_matched": r.frames_matched,
        }
