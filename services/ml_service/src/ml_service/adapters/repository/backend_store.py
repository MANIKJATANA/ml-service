"""Postgres read+write of the backend's ``events``/``media`` status (decisions/0027).

The ML worker reads the event's photo roster and **writes the status columns** on the
backend's own tables (via :mod:`ml_service.db.backend_tables`) — the single coupling to
the backend schema (decisions/0022). Both services share the same ``app`` Postgres, so
this reuses the ML sessionmaker; the ML service never calls the backend over HTTP.

The status *string values* are a cross-service contract with the backend's
``EventProcessingStatus`` / ``MediaProcessingStatus`` CHECK constraints — keep them in
lockstep with the backend enums.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ml_service.db.backend_tables import events as backend_events
from ml_service.db.backend_tables import media as backend_media
from ml_service.domain.models import BackendMedia, MediaType

# Contract with the backend's status CHECK constraints (decisions/0027, BP8a/0049).
_EVENT_PROCESSING = "processing"
_EVENT_COMPLETED = "completed"
_MEDIA_COMPLETED = "completed"
_MEDIA_FAILED = "failed"


def _opt_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


class PostgresBackendEventStore:
    """``BackendEventStore`` over an async SQLAlchemy sessionmaker (shared DB)."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def list_event_media(
        self, school_id: str, event_id: str
    ) -> list[BackendMedia]:
        sid = _opt_uuid(school_id)
        eid = _opt_uuid(event_id)
        if sid is None or eid is None:
            return []  # malformed id -> no roster (tenant-safe)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(
                    backend_media.c.id,
                    backend_media.c.storage_path,
                    backend_media.c.media_type,
                    backend_media.c.processing_status,
                )
                .where(
                    backend_media.c.school_id == sid,
                    backend_media.c.event_id == eid,
                )
                .order_by(backend_media.c.id)
            )
            roster: list[BackendMedia] = []
            for media_id, storage_path, media_type, status in result.all():
                try:
                    kind = MediaType(media_type)
                except ValueError:
                    continue  # unknown media_type -> skip defensively
                roster.append(
                    BackendMedia(
                        media_id=str(media_id),
                        media_uri=storage_path,
                        media_type=kind,
                        processing_status=status,
                    )
                )
            return roster

    async def mark_media_completed(self, school_id: str, media_id: str) -> None:
        # Tenant-scoped like every other write in the codebase (NFR-3): the id is always
        # roster-derived, but scoping the UPDATE keeps the invariant at the write seam.
        sid = _opt_uuid(school_id)
        key = _opt_uuid(media_id)
        if sid is None or key is None:
            return
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(backend_media)
                .where(backend_media.c.id == key, backend_media.c.school_id == sid)
                .values(processing_status=_MEDIA_COMPLETED, completed_at=func.now())
            )

    async def mark_media_failed(self, school_id: str, media_id: str) -> None:
        # BP8a: a photo the worker couldn't process. `failed` (not `completed`), so a
        # redistribute re-attempts it (the roster-skip is `== completed` only). No
        # completed_at — it never completed. Tenant-scoped like every write (NFR-3).
        sid = _opt_uuid(school_id)
        key = _opt_uuid(media_id)
        if sid is None or key is None:
            return
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(backend_media)
                .where(backend_media.c.id == key, backend_media.c.school_id == sid)
                .values(processing_status=_MEDIA_FAILED)
            )

    async def mark_event_processing(self, school_id: str, event_id: str) -> None:
        await self._set_event(
            school_id, event_id, status=_EVENT_PROCESSING, stamp_completed=False
        )

    async def mark_event_completed(self, school_id: str, event_id: str) -> None:
        await self._set_event(
            school_id, event_id, status=_EVENT_COMPLETED, stamp_completed=True
        )

    async def _set_event(
        self, school_id: str, event_id: str, *, status: str, stamp_completed: bool
    ) -> None:
        sid = _opt_uuid(school_id)
        key = _opt_uuid(event_id)
        if sid is None or key is None:
            return
        values: dict[str, object] = {"processing_status": status}
        if stamp_completed:
            values["completed_at"] = func.now()
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(backend_events)
                .where(backend_events.c.id == key, backend_events.c.school_id == sid)
                .values(**values)
            )
