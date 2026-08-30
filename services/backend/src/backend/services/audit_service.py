"""Access/download audit reads — the school-admin trust surfaces (BP8b, decisions/0050).

Ports-only (no HTTP, no RBAC): authorization is at the route (``audit:view``), tenant is the
caller's token ``school_id``. Reads the append-only ``download_audit`` rows (written
best-effort by ``GalleryService`` on each entitled download) and composes display data —
actor email, event name, subject-student name — from the backend's OWN rows, batched
in-Python (no N+1), never a cross-service SQL join. Two surfaces: a per-photo history and a
paginated, filterable school-wide log.

An actor/subject whose account was later deleted reads back with a ``None`` id (FK SET NULL);
the denormalized ``actor_role`` still shows in what capacity the download happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from backend.domain.errors import NotFoundError
from backend.domain.models import DownloadAuditEntry, User
from backend.domain.ports import (
    DownloadAuditRepository,
    EventRepository,
    MediaRepository,
    StudentRepository,
    UserRepository,
)

# The per-photo history returns the most recent downloads (the count is the true total).
_MEDIA_HISTORY_LIMIT = 200


@dataclass(frozen=True, slots=True)
class DownloadAuditView:
    """One download event with display data joined (actor email, event/student names)."""

    id: str
    media_id: str
    event_id: str
    event_name: str | None
    actor_user_id: str | None
    actor_email: str | None
    actor_role: str
    subject_student_id: str | None
    subject_student_name: str | None
    created_at: datetime


@dataclass(frozen=True, slots=True)
class MediaDownloadHistory:
    """A photo's download history: how many times total + the recent entries."""

    count: int
    entries: list[DownloadAuditView]


@dataclass(frozen=True, slots=True)
class DownloadLogPage:
    """One page of the school-wide access log + the unpaginated total (for the filter)."""

    items: list[DownloadAuditView]
    total: int
    limit: int
    offset: int


class AuditService:
    def __init__(
        self,
        audit: DownloadAuditRepository,
        media: MediaRepository,
        events: EventRepository,
        students: StudentRepository,
        users: UserRepository,
    ) -> None:
        self._audit = audit
        self._media = media
        self._events = events
        self._students = students
        self._users = users

    async def media_download_history(
        self, *, school_id: str, media_id: str
    ) -> MediaDownloadHistory:
        """Who downloaded one photo + when. 404 if the media isn't in the caller's school
        (tenant strictly from the token)."""
        if await self._media.get(school_id, media_id) is None:
            raise NotFoundError(f"media not found: {media_id}")
        entries = await self._audit.list_for_media(
            school_id, media_id, limit=_MEDIA_HISTORY_LIMIT
        )
        total = await self._audit.count_for_media(school_id, media_id)
        return MediaDownloadHistory(
            count=total, entries=await self._compose(school_id, entries)
        )

    async def school_download_log(
        self,
        *,
        school_id: str,
        limit: int,
        offset: int,
        event_id: str | None = None,
        student_id: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        actor_role: str | None = None,
    ) -> DownloadLogPage:
        """The school-wide access log, newest-first, optionally filtered by event/student, a
        date range (BP28a, inclusive ``created_from``/``created_to``), and actor role."""
        rows = await self._audit.list_recent(
            school_id,
            limit=limit,
            offset=offset,
            event_id=event_id,
            student_id=student_id,
            created_from=created_from,
            created_to=created_to,
            actor_role=actor_role,
        )
        total = await self._audit.count_recent(
            school_id,
            event_id=event_id,
            student_id=student_id,
            created_from=created_from,
            created_to=created_to,
            actor_role=actor_role,
        )
        return DownloadLogPage(
            items=await self._compose(school_id, rows),
            total=total,
            limit=limit,
            offset=offset,
        )

    # ---- internals -----------------------------------------------------

    async def _compose(
        self, school_id: str, rows: list[DownloadAuditEntry]
    ) -> list[DownloadAuditView]:
        """Join display data onto the raw audit rows — batched, no N+1."""
        if not rows:
            return []
        # De-rostered (BP9): fetch only the events/students this page references, not the
        # whole school — bounded by the page size.
        event_ids = list({r.event_id for r in rows})
        student_ids = list(
            {r.subject_student_id for r in rows if r.subject_student_id is not None}
        )
        events = {e.id: e for e in await self._events.list_by_ids(school_id, event_ids)}
        students = {
            s.id: s for s in await self._students.list_by_ids(school_id, student_ids)
        }
        # Actors are users (no per-school list method); fetch each distinct id once.
        actors: dict[str, User] = {}
        for r in rows:
            uid = r.actor_user_id
            if uid is None or uid in actors:
                continue
            user = await self._users.get(uid)
            if user is not None:
                actors[uid] = user
        out: list[DownloadAuditView] = []
        for r in rows:
            event = events.get(r.event_id)
            student = (
                students.get(r.subject_student_id)
                if r.subject_student_id is not None
                else None
            )
            actor = (
                actors.get(r.actor_user_id) if r.actor_user_id is not None else None
            )
            out.append(
                DownloadAuditView(
                    id=r.id,
                    media_id=r.media_id,
                    event_id=r.event_id,
                    event_name=event.name if event is not None else None,
                    actor_user_id=r.actor_user_id,
                    actor_email=actor.email if actor is not None else None,
                    actor_role=r.actor_role,
                    subject_student_id=r.subject_student_id,
                    subject_student_name=student.name if student is not None else None,
                    created_at=r.created_at,
                )
            )
        return out
