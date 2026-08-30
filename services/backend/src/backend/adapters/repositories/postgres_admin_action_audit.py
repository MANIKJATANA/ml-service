"""Postgres implementation of :class:`AdminActionAuditRepository` (BP28b, R4-A25).

Append-only audit of governance-lifecycle actions. ``record`` inserts one immutable row (in
its own transaction, so a best-effort audit never entangles the mutation's transaction); the
reads are tenant-scoped, newest-first, and return pure ``AdminActionAuditEntry`` value objects
the ``AdminActionAuditService`` composes the actor's current email onto (never a SQL join).
``action``/``target_type`` are matched against the DENORMALIZED columns; a row whose actor
account was later deleted keeps the row (its FK is SET NULL), so ``actor_user_id`` reads None
while the role/label survive.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.adapters.repositories._common import opt_uuid, req_uuid
from backend.db.models import AdminActionAudit as AuditRow
from backend.domain.models import AdminActionAuditEntry


def _to_entry(row: AuditRow) -> AdminActionAuditEntry:
    return AdminActionAuditEntry(
        id=str(row.id),
        school_id=str(row.school_id),
        actor_user_id=str(row.actor_user_id) if row.actor_user_id is not None else None,
        actor_role=row.actor_role,
        action=row.action,
        target_type=row.target_type,
        target_id=str(row.target_id) if row.target_id is not None else None,
        target_label=row.target_label,
        created_at=row.created_at,
    )


class PostgresAdminActionAuditRepository:
    """``AdminActionAuditRepository`` over an async SQLAlchemy sessionmaker."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(
        self,
        *,
        school_id: str,
        actor_user_id: str | None,
        actor_role: str,
        action: str,
        target_type: str,
        target_id: str | None,
        target_label: str | None,
    ) -> None:
        sid = req_uuid(school_id, field="school_id")
        aid = (
            req_uuid(actor_user_id, field="actor_user_id")
            if actor_user_id is not None
            else None
        )
        tid = (
            req_uuid(target_id, field="target_id") if target_id is not None else None
        )
        stmt = insert(AuditRow).values(
            school_id=sid,
            actor_user_id=aid,
            actor_role=actor_role,
            action=action,
            target_type=target_type,
            target_id=tid,
            target_label=target_label,
        )
        async with self._sessionmaker() as session, session.begin():
            await session.execute(stmt)

    async def list_recent(
        self,
        school_id: str,
        *,
        limit: int,
        offset: int,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_user_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> list[AdminActionAuditEntry]:
        sid = opt_uuid(school_id)
        if sid is None:
            return []
        conds = [AuditRow.school_id == sid]
        # action/target_type are DENORMALIZED columns (no join) — a deleted actor's rows still
        # match. target_id/actor_user_id are id equality (a malformed id → no rows).
        if action is not None:
            conds.append(AuditRow.action == action)
        if target_type is not None:
            conds.append(AuditRow.target_type == target_type)
        if target_id is not None:
            tid = opt_uuid(target_id)
            if tid is None:
                return []
            conds.append(AuditRow.target_id == tid)
        if actor_user_id is not None:
            aid = opt_uuid(actor_user_id)
            if aid is None:
                return []
            conds.append(AuditRow.actor_user_id == aid)
        if created_from is not None:
            conds.append(AuditRow.created_at >= created_from)
        if created_to is not None:
            conds.append(AuditRow.created_at <= created_to)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(AuditRow)
                .where(*conds)
                # id as a stable tiebreaker so same-instant rows never reorder across pages.
                .order_by(AuditRow.created_at.desc(), AuditRow.id.desc())
                .offset(offset)
                .limit(limit)
            )
            return [_to_entry(r) for r in result.scalars().all()]

    async def count_recent(
        self,
        school_id: str,
        *,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_user_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> int:
        sid = opt_uuid(school_id)
        if sid is None:
            return 0
        conds = [AuditRow.school_id == sid]
        if action is not None:
            conds.append(AuditRow.action == action)
        if target_type is not None:
            conds.append(AuditRow.target_type == target_type)
        if target_id is not None:
            tid = opt_uuid(target_id)
            if tid is None:
                return 0
            conds.append(AuditRow.target_id == tid)
        if actor_user_id is not None:
            aid = opt_uuid(actor_user_id)
            if aid is None:
                return 0
            conds.append(AuditRow.actor_user_id == aid)
        if created_from is not None:
            conds.append(AuditRow.created_at >= created_from)
        if created_to is not None:
            conds.append(AuditRow.created_at <= created_to)
        async with self._sessionmaker() as session:
            result = await session.execute(
                select(func.count()).select_from(AuditRow).where(*conds)
            )
            return int(result.scalar_one())
