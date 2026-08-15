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

# Contract with the backend's status CHECK constraints (decisions/0027, BP8a/0049, BP19a/0069).
_EVENT_QUEUED = "queued"
_EVENT_PROCESSING = "processing"
_EVENT_COMPLETED = "completed"
_EVENT_FAILED = "failed"
_MEDIA_COMPLETED = "completed"
_MEDIA_FAILED = "failed"

# BP19a: mark_event_failed may only flip a NON-terminal event. A stale dead-letter entry can
# survive a crash-between-mark-and-remove and be re-drained AFTER the operator retried and the
# event reached `completed`; without this guard the re-mark would clobber a genuinely-done
# event back to `failed` and strand it. So a `completed` (or `not_started`) event is never
# re-marked failed; a `failed` re-mark stays idempotent.
_FAILABLE_EVENT_STATES = (_EVENT_QUEUED, _EVENT_PROCESSING, _EVENT_FAILED)


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

    async def mark_event_failed(self, school_id: str, event_id: str) -> None:
        # BP19a: the event's job dead-lettered (retries exhausted). The worker's DLQ consumer
        # writes `failed` so the event stops looking like it's "processing" forever and becomes
        # retryable (the backend's Process guard allows a `failed` event). No completed_at — it
        # never completed. Tenant-scoped like every write (NFR-3). ``only_from`` keeps a stale
        # re-drain from clobbering an event that has since reached `completed`.
        await self._set_event(
            school_id,
            event_id,
            status=_EVENT_FAILED,
            stamp_completed=False,
            only_from=_FAILABLE_EVENT_STATES,
        )

    async def _set_event(
        self,
        school_id: str,
        event_id: str,
        *,
        status: str,
        stamp_completed: bool,
        only_from: tuple[str, ...] | None = None,
    ) -> None:
        sid = _opt_uuid(school_id)
        key = _opt_uuid(event_id)
        if sid is None or key is None:
            return
        values: dict[str, object] = {"processing_status": status}
        if stamp_completed:
            values["completed_at"] = func.now()
        stmt = update(backend_events).where(
            backend_events.c.id == key, backend_events.c.school_id == sid
        )
        if only_from is not None:
            # Only transition FROM one of these states (a no-op otherwise) — used by
            # mark_event_failed to never clobber a `completed` event back to `failed`.
            stmt = stmt.where(backend_events.c.processing_status.in_(only_from))
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt.values(**values))
