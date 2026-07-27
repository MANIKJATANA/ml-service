"""Postgres implementation of :class:`MediaRepository` (decisions/0027).

Reads are tenant-scoped (every ``get``/``list``/``status_counts`` takes ``school_id``),
enforcing tenant isolation at the query layer (decisions/0022). Recording a photo
enqueues nothing — processing is event-level, and the per-photo status column is written
by the ML worker directly (shared DB), so this repo only reads it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import Media as MediaRow
from backend.domain.models import Media, MediaProcessingStatus, MediaType


def _filtered_event(
    sid: uuid.UUID, eid: uuid.UUID, status: MediaProcessingStatus | None
) -> list[ColumnElement[bool]]:
    """The shared WHERE clauses for the paginated event-media reads (BP9)."""
    conds: list[ColumnElement[bool]] = [
        MediaRow.school_id == sid,
        MediaRow.event_id == eid,
    ]
    if status is not None:
        conds.append(MediaRow.processing_status == status.value)
    return conds


def _to_media(row: MediaRow) -> Media:
    return Media(
        id=str(row.id),
        school_id=str(row.school_id),
        event_id=str(row.event_id),
        storage_path=row.storage_path,
        media_type=MediaType(row.media_type),
        processing_status=MediaProcessingStatus(row.processing_status),
        completed_at=row.completed_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
        thumbnail_path=row.thumbnail_path,
    )


class PostgresMediaRepository:
    """``MediaRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        school_id: str,
        event_id: str,
        storage_path: str,
        media_type: MediaType,
        thumbnail_path: str | None = None,
    ) -> Media:
        sid = req_uuid(school_id, field="school_id")
        eid = req_uuid(event_id, field="event_id")
        async with self._sessionmaker() as session, session.begin():
            row = MediaRow(
                school_id=sid,
                event_id=eid,
                storage_path=storage_path,
                media_type=media_type.value,
                thumbnail_path=thumbnail_path,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_media(row)

    async def get(self, school_id: str, media_id: str) -> Media | None:
        sid = opt_uuid(school_id)
        mid = opt_uuid(media_id)
        if sid is None or mid is None:
            return None
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow).where(MediaRow.id == mid, MediaRow.school_id == sid)
            )
            row = result.scalar_one_or_none()
            return _to_media(row) if row is not None else None

    async def list_by_event(self, school_id: str, event_id: str) -> list[Media]:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow)
                .where(MediaRow.school_id == sid, MediaRow.event_id == eid)
                .order_by(MediaRow.created_at, MediaRow.id)  # stable on ties
            )
            return [_to_media(r) for r in result.scalars().all()]

    async def list_page_by_event(
        self,
        school_id: str,
        event_id: str,
        *,
        limit: int,
        offset: int,
        status: MediaProcessingStatus | None = None,
    ) -> list[Media]:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow)
                .where(*_filtered_event(sid, eid, status))
                .order_by(MediaRow.created_at, MediaRow.id)  # stable on ties
                .offset(offset)
                .limit(limit)
            )
            return [_to_media(r) for r in result.scalars().all()]

    async def count_page_by_event(
        self,
        school_id: str,
        event_id: str,
        *,
        status: MediaProcessingStatus | None = None,
    ) -> int:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(MediaRow)
                .where(*_filtered_event(sid, eid, status))
            )
            return int(result.scalar_one())

    async def list_by_ids(
        self, school_id: str, media_ids: Sequence[str]
    ) -> list[Media]:
        """Bulk-load media by id within one tenant (decisions/0028).

        Used by the galleries to hydrate the media a student appears in. Tenant-scoped
        and defensive: malformed ids are dropped, and a matches row pointing at an
        already-deleted/foreign media simply doesn't come back."""
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        ids = [mid for mid in (opt_uuid(m) for m in media_ids) if mid is not None]
        if not ids:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow)
                .where(MediaRow.school_id == sid, MediaRow.id.in_(ids))
                .order_by(MediaRow.created_at, MediaRow.id)  # stable on ties
            )
            return [_to_media(r) for r in result.scalars().all()]

    async def status_counts(
        self, school_id: str, event_id: str
    ) -> dict[MediaProcessingStatus, int]:
        counts = {s: 0 for s in MediaProcessingStatus}
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return counts
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow.processing_status, func.count())
                .where(MediaRow.school_id == sid, MediaRow.event_id == eid)
                .group_by(MediaRow.processing_status)
            )
            for status_value, n in result.all():
                counts[MediaProcessingStatus(status_value)] = n
        return counts

    async def counts_by_event(self, school_id: str) -> dict[str, int]:
        """Photo count per event for one school (BP2 events list).

        One grouped scan of the tenant's ``media`` slice (``ix_media_event``); keys are
        canonical UUID strings, matching the domain event ids."""
        sid = opt_uuid(school_id)
        if sid is None:
            return {}
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow.event_id, func.count())
                .where(MediaRow.school_id == sid)
                .group_by(MediaRow.event_id)
            )
            return {str(event_id): n for event_id, n in result.all()}

    async def monthly_upload_counts(self, school_id: str) -> dict[str, int]:
        """Photos/videos uploaded per calendar month for a school (BP14 trend), keyed
        ``'YYYY-MM'``.

        One grouped scan (``date_trunc('month', created_at)``, UTC), tenant-scoped."""
        sid = opt_uuid(school_id)
        if sid is None:
            return {}
        month = func.to_char(func.date_trunc("month", MediaRow.created_at), "YYYY-MM")
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(month, func.count())
                .where(MediaRow.school_id == sid)
                .group_by(month)
            )
            return {str(m): n for m, n in result.all()}

    async def school_status_counts(
        self, school_id: str
    ) -> dict[MediaProcessingStatus, int]:
        """All of a school's photos grouped by processing status (BP1 dashboard).

        The event-agnostic sibling of ``status_counts``: one grouped scan over the
        tenant's ``media`` slice; total photos = the sum of the returned values."""
        counts = {s: 0 for s in MediaProcessingStatus}
        sid = opt_uuid(school_id)
        if sid is None:
            return counts
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(MediaRow.processing_status, func.count())
                .where(MediaRow.school_id == sid)
                .group_by(MediaRow.processing_status)
            )
            for status_value, n in result.all():
                counts[MediaProcessingStatus(status_value)] = n
        return counts
