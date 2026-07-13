"""Log notification channel — structured + PII-free (BP4, decisions/0041).

The default channel and a verifiable stand-in until a real outbound channel (email /
WhatsApp) is configured via ``BE_NOTIFICATION_CHANNELS``. Emits ids + counts only — never
the student's name or contact address (PII discipline, cf. observability/logging.py).
"""

from __future__ import annotations

import structlog

from backend.domain.models import NotificationEvent

_log = structlog.get_logger("backend.notifications")


class LogNotificationChannel:
    """``NotificationChannel`` that logs a structured 'announced' event."""

    async def notify(self, event: NotificationEvent) -> None:
        _log.info(
            "notification_announced",
            channel="log",
            school_id=event.school_id,
            event_id=event.event_id,
            student_id=event.student_id,
            media_count=event.media_count,
        )
