"""Access/download audit API schemas (BP8b, decisions/0050).

Read-only, school-admin-facing. One entry describes a single recorded download: who (actor
email + role — a deleted actor keeps the role, drops the email), what (media + its event),
and — for a student self-download — which student they are. All ids/names are joined from
backend-owned rows by ``AuditService``.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from backend.services.audit_service import (
    DownloadAuditView,
    DownloadLogPage,
    MediaDownloadHistory,
)

__all__ = [
    "DownloadAuditEntryResponse",
    "DownloadLogPageResponse",
    "MediaDownloadLogResponse",
]


class DownloadAuditEntryResponse(BaseModel):
    """One recorded download, display-composed."""

    id: str
    media_id: str
    event_id: str
    event_name: str | None
    actor_user_id: str | None
    actor_email: str | None
    actor_role: str
    subject_student_id: str | None
    subject_student_name: str | None
    downloaded_at: datetime

    @classmethod
    def from_view(cls, view: DownloadAuditView) -> DownloadAuditEntryResponse:
        return cls(
            id=view.id,
            media_id=view.media_id,
            event_id=view.event_id,
            event_name=view.event_name,
            actor_user_id=view.actor_user_id,
            actor_email=view.actor_email,
            actor_role=view.actor_role,
            subject_student_id=view.subject_student_id,
            subject_student_name=view.subject_student_name,
            downloaded_at=view.created_at,
        )


class MediaDownloadLogResponse(BaseModel):
    """A photo's download history — total count + the recent entries."""

    count: int
    entries: list[DownloadAuditEntryResponse]

    @classmethod
    def from_view(cls, view: MediaDownloadHistory) -> MediaDownloadLogResponse:
        return cls(
            count=view.count,
            entries=[
                DownloadAuditEntryResponse.from_view(e) for e in view.entries
            ],
        )


class DownloadLogPageResponse(BaseModel):
    """One page of the school-wide access log + the unpaginated total."""

    items: list[DownloadAuditEntryResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: DownloadLogPage) -> DownloadLogPageResponse:
        return cls(
            items=[DownloadAuditEntryResponse.from_view(i) for i in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
