"""Notification (distribution) API schemas (BP4, decisions/0041)."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel

from backend.services.notification_service import (
    NotificationRoster,
    StudentNotification,
)

__all__ = [
    "MyNotificationsResponse",
    "NotifyResultResponse",
    "NotificationRosterResponse",
]


class StudentNotificationItem(BaseModel):
    """One announced event a student appears in + whether it's still unseen."""

    event_id: str
    name: str
    event_date: date | None
    media_count: int
    unseen: bool


class MyNotificationsResponse(BaseModel):
    """The student's "new photos" signal: an unseen tally (the badge) + the announced
    events (newest first)."""

    unseen_count: int
    events: list[StudentNotificationItem]

    @classmethod
    def from_views(cls, views: list[StudentNotification]) -> MyNotificationsResponse:
        return cls(
            unseen_count=sum(1 for v in views if v.unseen),
            events=[
                StudentNotificationItem(
                    event_id=v.event.id,
                    name=v.event.name,
                    event_date=v.event.event_date,
                    media_count=v.media_count,
                    unseen=v.unseen,
                )
                for v in views
            ],
        )


class NotifyResultResponse(BaseModel):
    """The result of a manual "Notify students" push."""

    notified: int


class RosterEntryResponse(BaseModel):
    student_id: str
    name: str
    media_count: int
    seen: bool
    # BP23: the persistent ever-opened time (distinct from ``seen``, which resets on
    # re-announce) + how many of the event's photos the student has saved.
    first_seen_at: datetime | None = None
    download_count: int = 0


class NotificationRosterResponse(BaseModel):
    """The staff "who's been notified / seen" view for one event."""

    announced: bool
    auto_notify: bool
    notified_at: datetime | None
    notified_count: int
    seen_count: int
    students: list[RosterEntryResponse]

    @classmethod
    def from_roster(cls, roster: NotificationRoster) -> NotificationRosterResponse:
        # "notified" = everyone matched once the event is announced; else nobody yet.
        notified_count = len(roster.entries) if roster.announced else 0
        return cls(
            announced=roster.announced,
            auto_notify=roster.auto_notify,
            notified_at=roster.notified_at,
            notified_count=notified_count,
            seen_count=sum(1 for e in roster.entries if e.seen),
            students=[
                RosterEntryResponse(
                    student_id=e.student.id,
                    name=e.student.name,
                    media_count=e.media_count,
                    seen=e.seen,
                    first_seen_at=e.first_seen_at,
                    download_count=e.download_count,
                )
                for e in roster.entries
            ],
        )
