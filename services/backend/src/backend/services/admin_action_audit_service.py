"""Admin-action audit reads — the governance actor trail (BP28b, R4-A25).

Ports-only (no HTTP, no RBAC): authorization is at the route (``audit:view``), tenant is the
caller's token ``school_id``. Reads the append-only ``admin_action_audit`` rows (written
best-effort by the single-writer services after each governance mutation) and composes the
actor's CURRENT email from the backend's OWN ``users`` rows — batched in-Python (no N+1), never
a cross-service SQL join. Mirrors ``AuditService``.

An actor whose account was later deleted reads back with ``actor_user_id``/``actor_email`` =
None (FK SET NULL); the denormalized ``actor_role`` + ``target_label`` still show what happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.domain.models import AdminActionAuditEntry, User
from backend.domain.ports import AdminActionAuditRepository, UserRepository


@dataclass(frozen=True, slots=True)
class AdminActionView:
    """One recorded governance action with the actor's current email joined."""

    id: str
    actor_user_id: str | None
    actor_email: str | None
    actor_role: str
    action: str
    target_type: str
    target_id: str | None
    target_label: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AdminActionLogPage:
    """One page of the admin-action log + the unpaginated total (for the pager)."""

    items: list[AdminActionView]
    total: int
    limit: int
    offset: int


class AdminActionAuditService:
    def __init__(
        self, audit: AdminActionAuditRepository, users: UserRepository
    ) -> None:
        self._audit = audit
        self._users = users

    async def school_action_log(
        self,
        *,
        school_id: str,
        limit: int,
        offset: int,
        action: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        actor_user_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
    ) -> AdminActionLogPage:
        """The school-wide admin-action log, newest-first, optionally filtered by action,
        target (type/id), actor, and an inclusive ``created_from``/``created_to`` date range.
        Tenant strictly from the token."""
        rows = await self._audit.list_recent(
            school_id,
            limit=limit,
            offset=offset,
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor_user_id=actor_user_id,
            created_from=created_from,
            created_to=created_to,
        )
        total = await self._audit.count_recent(
            school_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            actor_user_id=actor_user_id,
            created_from=created_from,
            created_to=created_to,
        )
        return AdminActionLogPage(
            items=await self._compose(rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    # ---- internals -----------------------------------------------------

    async def _compose(
        self, rows: list[AdminActionAuditEntry]
    ) -> list[AdminActionView]:
        """Join the actor's current email onto the raw rows — batched, no N+1 (mirrors
        ``AuditService._compose``: users have no per-school list method, so fetch each
        distinct actor id once)."""
        if not rows:
            return []
        actors: dict[str, User] = {}
        for r in rows:
            uid = r.actor_user_id
            if uid is None or uid in actors:
                continue
            user = await self._users.get(uid)
            if user is not None:
                actors[uid] = user
        out: list[AdminActionView] = []
        for r in rows:
            actor = (
                actors.get(r.actor_user_id) if r.actor_user_id is not None else None
            )
            out.append(
                AdminActionView(
                    id=r.id,
                    actor_user_id=r.actor_user_id,
                    actor_email=actor.email if actor is not None else None,
                    actor_role=r.actor_role,
                    action=r.action,
                    target_type=r.target_type,
                    target_id=r.target_id,
                    target_label=r.target_label,
                    created_at=r.created_at,
                )
            )
        return out
