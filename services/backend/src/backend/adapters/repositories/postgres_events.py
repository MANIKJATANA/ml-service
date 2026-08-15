"""Postgres implementation of :class:`EventRepository` (decisions/0027).

Reads are tenant-scoped: every ``get``/``list_by_school``/``update`` takes ``school_id``
so an event that belongs to another school is invisible (returned as ``None``/absent),
enforcing tenant isolation at the query layer (decisions/0022). BP11b LEFT JOINs
``event_categories`` on the object reads to carry the category name for display.

``set_processing`` is only used by the backend to set ``queued`` on Process (the ML
worker owns the ``processing``/``completed`` writes); it stamps a fresh ``enqueued_at``.
It **keeps** ``completed_at`` set-forward across a redistribute (BP4, decisions/0041) — the
prior clear-on-requeue was dropped so an auto-announced event doesn't un-announce mid-run.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime

from sqlalchemy import (
    ColumnElement,
    Select,
    and_,
    false,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import (
    LIKE_ESCAPE,
    ilike_term,
    opt_uuid,
    req_uuid,
)
from backend.db.models import Event as EventRow
from backend.db.models import EventCategory as EventCategoryRow
from backend.db.models import Media as MediaRow
from backend.db.models import StudentGroup as StudentGroupRow
from backend.domain.models import (
    Event,
    EventProcessingStatus,
    EventRollup,
    EventSort,
    EventStatus,
    MediaProcessingStatus,
)

# Processing states that count as "currently distributing" for the dashboard rollup.
_IN_FLIGHT = (EventProcessingStatus.QUEUED.value, EventProcessingStatus.PROCESSING.value)

# Row-native sort columns (BP9); count sorts (media/matched/needs_review) take the id-scan
# path in the service, so a stray one falls back to ``event_date``.
_SORT_COLS = {
    EventSort.EVENT_DATE: EventRow.event_date,
    EventSort.NAME: EventRow.name,
    EventSort.CREATED_AT: EventRow.created_at,
}


def _to_event(
    row: EventRow,
    category_name: str | None = None,
    group_name: str | None = None,
) -> Event:
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
        term=row.term,
        category_id=(
            str(row.category_id) if row.category_id is not None else None
        ),
        category_name=category_name,
        student_group_id=(
            str(row.student_group_id) if row.student_group_id is not None else None
        ),
        student_group_name=group_name,
    )


class PostgresEventRepository:
    """``EventRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    @staticmethod
    def _select_with_names() -> Select[tuple[EventRow, str, str]]:
        """The object read: event + its category name + its class name (two LEFT JOINs, both
        nullable). Returned rows are ``(EventRow, category_name, group_name)`` — each name is
        ``None`` when the event is uncategorized / untagged (BP11b + BP11c)."""
        return (
            select(EventRow, EventCategoryRow.name, StudentGroupRow.name)
            .outerjoin(
                EventCategoryRow, EventRow.category_id == EventCategoryRow.id
            )
            .outerjoin(
                StudentGroupRow, EventRow.student_group_id == StudentGroupRow.id
            )
        )

    @staticmethod
    async def _names(
        session: AsyncSession,
        category_id: uuid.UUID | None,
        student_group_id: uuid.UUID | None,
    ) -> tuple[str | None, str | None]:
        """The category + class names for a just-written event (so create/update return them)."""
        category_name = (
            None
            if category_id is None
            else (
                await session.execute(
                    select(EventCategoryRow.name).where(
                        EventCategoryRow.id == category_id
                    )
                )
            ).scalar_one_or_none()
        )
        group_name = (
            None
            if student_group_id is None
            else (
                await session.execute(
                    select(StudentGroupRow.name).where(
                        StudentGroupRow.id == student_group_id
                    )
                )
            ).scalar_one_or_none()
        )
        return category_name, group_name

    async def create(
        self,
        *,
        school_id: str,
        name: str,
        description: str | None,
        event_date: date | None,
        created_by: str | None,
        category_id: str | None = None,
        term: str | None = None,
        student_group_id: str | None = None,
    ) -> Event:
        sid = req_uuid(school_id, field="school_id")
        cby = req_uuid(created_by, field="created_by") if created_by is not None else None
        cat = (
            req_uuid(category_id, field="category_id")
            if category_id is not None
            else None
        )
        grp = (
            req_uuid(student_group_id, field="student_group_id")
            if student_group_id is not None
            else None
        )
        async with self._sessionmaker() as session, session.begin():
            row = EventRow(
                school_id=sid,
                name=name,
                description=description,
                event_date=event_date,
                created_by=cby,
                category_id=cat,
                term=term,
                student_group_id=grp,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            cat_name, grp_name = await self._names(
                session, row.category_id, row.student_group_id
            )
            return _to_event(row, cat_name, grp_name)

    async def get(self, school_id: str, event_id: str) -> Event | None:
        sid = opt_uuid(school_id)
        eid = opt_uuid(event_id)
        if sid is None or eid is None:
            return None  # malformed id -> not found (tenant-safe)
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_names().where(
                    EventRow.id == eid, EventRow.school_id == sid
                )
            )
            row = result.one_or_none()
            return _to_event(row[0], row[1], row[2]) if row is not None else None

    async def list_by_school(self, school_id: str) -> list[Event]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_names()
                .where(EventRow.school_id == sid)
                .order_by(EventRow.created_at, EventRow.id)  # stable on ties
            )
            return [_to_event(r[0], r[1], r[2]) for r in result.all()]

    def _filtered(
        self,
        sid: uuid.UUID,
        q: str | None,
        status: EventStatus | None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[ColumnElement[bool]]:
        """The shared WHERE clauses for the paginated events reads (BP9 + BP11b + BP11c
        filters). A malformed ``category_id``/``student_group_id`` yields no rows (never an
        ``IS NULL`` that would wrongly match untagged events). ``date_from``/``date_to`` bound
        ``event_date`` — a null date is excluded (which the calendar wants). BP11c
        ``scope_group_ids`` (a teacher's focus) matches events tagged to those classes **OR
        untagged/school-wide** — an empty scope leaves only the untagged."""
        conds: list[ColumnElement[bool]] = [EventRow.school_id == sid]
        if status is not None:
            conds.append(EventRow.status == status.value)
        if category_id is not None:
            cid = opt_uuid(category_id)
            conds.append(EventRow.category_id == cid if cid is not None else false())
        if term is not None:
            conds.append(EventRow.term == term)
        if date_from is not None:
            conds.append(EventRow.event_date >= date_from)
        if date_to is not None:
            conds.append(EventRow.event_date <= date_to)
        if student_group_id is not None:
            gid = opt_uuid(student_group_id)
            conds.append(
                EventRow.student_group_id == gid if gid is not None else false()
            )
        if scope_group_ids is not None:
            gids = [
                g for g in (opt_uuid(x) for x in scope_group_ids) if g is not None
            ]
            # Untagged (school-wide) events show for every focused teacher; add the scoped
            # classes when the teacher has any (an empty scope leaves only the untagged).
            conds.append(
                EventRow.student_group_id.is_(None)
                if not gids
                else or_(
                    EventRow.student_group_id.is_(None),
                    EventRow.student_group_id.in_(gids),
                )
            )
        if q:
            conds.append(EventRow.name.ilike(ilike_term(q), escape=LIKE_ESCAPE))
        return conds

    async def list_page(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        q: str | None = None,
        sort: EventSort = EventSort.EVENT_DATE,
        descending: bool = True,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[Event]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        col = _SORT_COLS.get(sort, EventRow.event_date)
        order = (
            (col.desc(), EventRow.id.desc())
            if descending
            else (col.asc(), EventRow.id.asc())
        )
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_names()
                .where(
                    *self._filtered(
                        sid, q, status, category_id, term, date_from, date_to,
                        student_group_id, scope_group_ids,
                    )
                )
                .order_by(*order)
                .offset(offset)
                .limit(limit)
            )
            return [_to_event(r[0], r[1], r[2]) for r in result.all()]

    async def count_page(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count())
                .select_from(EventRow)
                .where(
                    *self._filtered(
                        sid, q, status, category_id, term, date_from, date_to,
                        student_group_id, scope_group_ids,
                    )
                )
            )
            return int(result.scalar_one())

    async def list_ids(
        self,
        school_id: str,
        *,
        q: str | None = None,
        status: EventStatus | None = None,
        category_id: str | None = None,
        term: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        student_group_id: str | None = None,
        scope_group_ids: Sequence[str] | None = None,
    ) -> list[str]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow.id).where(
                    *self._filtered(
                        sid, q, status, category_id, term, date_from, date_to,
                        student_group_id, scope_group_ids,
                    )
                )
            )
            return [str(r) for r in result.scalars().all()]

    async def list_terms(self, school_id: str) -> list[str]:
        """Distinct non-null ``term`` values for a school, sorted (BP11b — the FE term filter)."""
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow.term)
                .where(EventRow.school_id == sid, EventRow.term.is_not(None))
                .distinct()
                .order_by(EventRow.term)
            )
            return [t for t in result.scalars().all() if t is not None]

    async def list_by_ids(
        self, school_id: str, event_ids: Sequence[str]
    ) -> list[Event]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        ids = [eid for eid in (opt_uuid(e) for e in event_ids) if eid is not None]
        if not ids:
            return []
        async with self._sessionmaker() as session:
            result = await session.execute(
                self._select_with_names()
                .where(EventRow.school_id == sid, EventRow.id.in_(ids))
                .order_by(EventRow.created_at, EventRow.id)  # stable on ties
            )
            return [_to_event(r[0], r[1], r[2]) for r in result.all()]

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

    async def count_active_with_pending_media(self, school_id: str) -> int:
        """Active, not-in-flight events that have >=1 still-``pending`` photo (BP1 alert,
        widened in BP19c).

        The "you have photos that need processing" signal. BP19c widens the old
        never-processed-only predicate (``processing_status == not_started``) to catch a
        **second batch** too — new photos on an already-``completed`` (or ``failed``) event —
        by keying on **pending media** rather than the event's status. In-flight events
        (``queued``/``processing``) are excluded (already being worked), as are **archived**
        events (you can't Process one — the route 400s). One correlated ``EXISTS`` on pending
        media; both sides tenant-scoped by ``school_id``."""
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        has_pending_media = (
            select(MediaRow.id)
            .where(
                MediaRow.event_id == EventRow.id,
                MediaRow.school_id == sid,
                MediaRow.processing_status == MediaProcessingStatus.PENDING.value,
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
                    EventRow.processing_status.not_in(_IN_FLIGHT),
                    has_pending_media,
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

    async def distributed_counts_by_school(self) -> dict[str, int]:
        """Announced events per school across all schools (BP14 estate funnel).

        The cross-tenant sibling of ``count_distributed`` — same "announced" predicate
        (manual ``notified_at`` OR auto-notify + ``completed_at``). One grouped scan,
        cross-tenant (reachable only behind ``school:manage``)."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow.school_id, func.count())
                .where(
                    or_(
                        EventRow.notified_at.is_not(None),
                        and_(
                            EventRow.auto_notify.is_(True),
                            EventRow.completed_at.is_not(None),
                        ),
                    )
                )
                .group_by(EventRow.school_id)
            )
            return {str(school_id): n for school_id, n in result.all()}

    async def recent_event_counts_by_school(
        self, since: datetime
    ) -> dict[str, int]:
        """Events created at/after ``since`` per school (BP14 stalled-school heuristic).

        One grouped scan, cross-tenant (reachable only behind ``school:manage``)."""
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(EventRow.school_id, func.count())
                .where(EventRow.created_at >= since)
                .group_by(EventRow.school_id)
            )
            return {str(school_id): n for school_id, n in result.all()}

    async def monthly_event_date_counts(self, school_id: str) -> dict[str, int]:
        """Events per calendar month by their ``event_date`` (BP14 trend), keyed ``'YYYY-MM'``.

        Buckets on the event's own date (when it happened), not ``created_at``; undated events
        are excluded. One grouped scan, tenant-scoped."""
        sid = opt_uuid(school_id)
        if sid is None:
            return {}
        month = func.to_char(EventRow.event_date, "YYYY-MM")
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(month, func.count())
                .where(
                    EventRow.school_id == sid,
                    EventRow.event_date.is_not(None),
                )
                .group_by(month)
            )
            return {str(m): n for m, n in result.all()}

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
        category_id: str | None = None,
        term: str | None = None,
        student_group_id: str | None = None,
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
            # means "leave unchanged" (so term/category/class can't be cleared to null —
            # BP11b/BP11c, consistent with description/event_date, decisions/0027).
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
            if category_id is not None:
                row.category_id = req_uuid(category_id, field="category_id")
            if term is not None:
                row.term = term
            if student_group_id is not None:
                row.student_group_id = req_uuid(
                    student_group_id, field="student_group_id"
                )
            await session.flush()
            await session.refresh(row)
            cat_name, grp_name = await self._names(
                session, row.category_id, row.student_group_id
            )
            return _to_event(row, cat_name, grp_name)

    async def set_status_bulk(
        self, school_id: str, event_ids: Sequence[str], *, status: EventStatus
    ) -> int:
        """Set the lifecycle status on many events in one tenant-scoped UPDATE (BP13). Only rows
        whose ``school_id`` matches are touched (a foreign/malformed id is silently skipped);
        returns the count updated."""
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        ids = [eid for eid in (opt_uuid(e) for e in event_ids) if eid is not None]
        if not ids:
            return 0
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(
                update(EventRow)
                .where(EventRow.school_id == sid, EventRow.id.in_(ids))
                .values(status=status.value)
            )
            return int(result.rowcount or 0)  # type: ignore[attr-defined]

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
