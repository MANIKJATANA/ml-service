"""Postgres implementation of :class:`EventRepository` (decisions/0027).

Reads are tenant-scoped: every ``get``/``list_by_school``/``update`` takes ``school_id``
so an event that belongs to another school is invisible (returned as ``None``/absent),
enforcing tenant isolation at the query layer (decisions/0022).

``set_processing`` is only used by the backend to set ``queued`` on Process (the ML
worker owns the ``processing``/``completed`` writes); it stamps a fresh ``enqueued_at``.
It **keeps** ``completed_at`` set-forward across a redistribute (BP4, decisions/0041) — the
prior clear-on-requeue was dropped so an auto-announced event doesn't un-announce mid-run.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import Event as EventRow
from backend.db.models import Media as MediaRow
from backend.domain.models import (
    Event,
    EventProcessingStatus,
    EventRollup,
    EventStatus,
)

# Processing states that count as "currently distributing" for the dashboard rollup.
_IN_FLIGHT = (EventProcessingStatus.QUEUED.value, EventProcessingStatus.PROCESSING.value)


def _to_event(row: EventRow) -> Event:
    return Event(
        id=str(row.id),
        school_id=str(row.school_id),
        name=row.name,
        description=row.description,
        event_date=row.event_date,
        created_by=str(row.created_by) if row.created_by is not None else None,
        status=EventStatus(row.status),
        processing_status=EventProcessingStatus(row.processing_status),
        enqueued_at=row.enqueued_at,
        completed_at=row.completed_at,
        auto_notify=row.auto_notify,
        notified_at=row.notified_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresEventRepository:
    """``EventRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def create(
        self,
        *,
        school_id: str,
        name: str,
        description: str | None,
        event_date: date | None,
        created_by: str | None,
    ) -> Event:
        sid = req_uuid(school_id, field="school_id")
        cby = req_uuid(created_by, field="created_by") if created_by is not None else None
        async with self._sessionmaker() as session, session.begin():
            row = EventRow(
                school_id=sid,
                name=name,
                description=description,
                event_date=event_date,
                created_by=cby,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _to_event(row)

    async def get(self, school_id: str, event_id: str) -> Event | None:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return None  # malformed id -> not found (tenant-safe)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow).where(EventRow.id == eid, EventRow.school_id == sid)
            )
            row = result.scalar_one_or_none()
            return _to_event(row) if row is not None else None

    async def list_by_school(self, school_id: str) -> list[Event]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow)
                .where(EventRow.school_id == sid)
                .order_by(EventRow.created_at, EventRow.id)  # stable on ties
            )
            return [_to_event(r) for r in result.scalars().all()]

    async def status_counts(self, school_id: str) -> EventRollup:
        """A school's events counted by lifecycle + in-flight state (BP1 dashboard).

        One grouped scan (``ix_events_school``) over ``(status, processing_status)``,
        folded into the rollup: ``active``/``archived`` from the lifecycle column,
        ``processing`` = rows whose ``processing_status`` is queued or processing."""
        sid = opt_uuid(school_id)
        if sid is None:
            return EventRollup(total=0, active=0, archived=0, processing=0)
        total = active = archived = processing = 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow.status, EventRow.processing_status, func.count())
                .where(EventRow.school_id == sid)
                .group_by(EventRow.status, EventRow.processing_status)
            )
            for status_value, processing_value, n in result.all():
                total += n
                if status_value == EventStatus.ACTIVE.value:
                    active += n
                elif status_value == EventStatus.ARCHIVED.value:
                    archived += n
                if processing_value in _IN_FLIGHT:
                    processing += n
        return EventRollup(
            total=total, active=active, archived=archived, processing=processing
        )

    async def count_not_started_with_media(self, school_id: str) -> int:
        """Active events that have >=1 photo but were never distributed (BP1 alert).

        The "you uploaded photos but didn't press Process" signal: ``processing_status``
        still ``not_started`` yet a ``media`` row exists. **Archived events are excluded**
        — you can't Process an archived event (the route 400s), so surfacing one as
        "ready to distribute" would point staff at an un-actionable event. One correlated
        ``EXISTS`` query; both sides are tenant-scoped by ``school_id``."""
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        has_media = (
            select(MediaRow.id)
            .where(
                MediaRow.event_id == EventRow.id,
                MediaRow.school_id == sid,
            )
            .exists()
        )
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(EventRow)
                .where(
                    EventRow.school_id == sid,
                    EventRow.status == EventStatus.ACTIVE.value,
                    EventRow.processing_status
                    == EventProcessingStatus.NOT_STARTED.value,
                    has_media,
                )
            )
            return int(result.scalar_one())

    async def count_distributed(self, school_id: str) -> int:
        """Events that have been announced to students — the first-run "distributed" step.

        Mirrors BP4's event-level "announced" predicate (decisions/0041): a manual
        ``notified_at`` push **OR** an ``auto_notify`` event that has ``completed_at``
        (auto-announced on completion). One indexed scan, tenant-scoped. Powers the
        setup-checklist's last step (BP7a) — status-agnostic (an archived event that was
        distributed still counts as "you've distributed once")."""
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(EventRow)
                .where(
                    EventRow.school_id == sid,
                    or_(
                        EventRow.notified_at.is_not(None),
                        and_(
                            EventRow.auto_notify.is_(True),
                            EventRow.completed_at.is_not(None),
                        ),
                    ),
                )
            )
            return int(result.scalar_one())

    async def counts_by_school(self) -> dict[str, int]:
        """Events per school across all schools (BP2 platform rollup).

        One grouped scan; cross-tenant on purpose (reachable only behind
        ``school:manage``). Keys are canonical UUID strings."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow.school_id, func.count()).group_by(EventRow.school_id)
            )
            return {str(school_id): n for school_id, n in result.all()}

    async def update(
        self,
        school_id: str,
        event_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        event_date: date | None = None,
        status: EventStatus | None = None,
        auto_notify: bool | None = None,
    ) -> Event | None:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return None
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                select(EventRow).where(EventRow.id == eid, EventRow.school_id == sid)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            # Only the fields the caller supplied are changed (partial update); a None
            # means "leave unchanged".
            if name is not None:
                row.name = name
            if description is not None:
                row.description = description
            if event_date is not None:
                row.event_date = event_date
            if status is not None:
                row.status = status.value
            if auto_notify is not None:
                row.auto_notify = auto_notify
            await session.flush()
            await session.refresh(row)
            return _to_event(row)

    async def set_processing(
        self, event_id: str, *, status: EventProcessingStatus
    ) -> None:
        # The backend only ever sets ``queued`` on Process (the ML worker owns the
        # processing/completed writes, decisions/0027). Stamp ``enqueued_at``. NB (BP4,
        # decisions/0041): ``completed_at`` is NO LONGER cleared on a redistribute — it is
        # set-forward (the last completion time), so an auto-announced event doesn't
        # un-announce mid-reprocess and the announce-time compare stays well-defined.
        key = req_uuid(event_id, field="event_id")
        values: dict[str, object] = {"processing_status": status.value}
        if status is EventProcessingStatus.QUEUED:
            values["enqueued_at"] = func.now()
        elif status is EventProcessingStatus.COMPLETED:
            values["completed_at"] = func.now()
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(EventRow).where(EventRow.id == key).values(**values)
            )

    async def mark_notified(self, event_id: str) -> None:
        """Stamp ``notified_at = now()`` (a manual "Notify students" push; BP4)."""
        key = req_uuid(event_id, field="event_id")
        async with self._sessionmaker() as session, session.begin():
            await session.execute(
                update(EventRow).where(EventRow.id == key).values(notified_at=func.now())
            )
