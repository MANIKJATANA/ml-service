"""Composite notifier — fans out to the configured channels (BP4, decisions/0041).

Structurally a ``NotificationChannel`` itself, so the service depends on one seam whether
zero, one, or many channels are configured. Best-effort: a channel that raises is logged
and skipped, so one channel being down never blocks the others nor fails the request that
triggered the announce. An empty channel list is a no-op (notifications disabled).
"""

from __future__ import annotations

from collections.abc import Sequence

import structlog

from backend.domain.models import NotificationEvent
from backend.domain.ports import NotificationChannel

_log = structlog.get_logger(__name__)


class CompositeNotifier:
    def __init__(self, channels: Sequence[NotificationChannel]) -> None:
        self._channels = list(channels)

    async def notify(self, event: NotificationEvent) -> None:
        for channel in self._channels:
            try:
                await channel.notify(event)
            except Exception:  # best-effort: one channel down must not block the rest
                _log.warning(
                    "notification_channel_failed",
                    channel=type(channel).__name__,
                    school_id=event.school_id,
                    event_id=event.event_id,
                    student_id=event.student_id,
                    exc_info=True,
                )
