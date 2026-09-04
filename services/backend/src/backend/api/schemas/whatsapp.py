"""WhatsApp send API schemas (W2).

Staff-facing (``whatsapp:send``). Schools no longer configure WhatsApp — the per-school config
request/response were removed in 0099 (the platform admin owns it all; see
``api/schemas/platform_config.py``). This module now holds only the send request + per-media
results.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.domain.models import WhatsAppSendSummary

__all__ = [
    "WhatsAppSendRequest",
    "WhatsAppSendResponse",
    "WhatsAppSendResultResponse",
]

# The most media ids one send request can carry (reuses the students bulk cap → 422 over it).
_MAX_SEND_MEDIA_IDS = 1000


class WhatsAppSendRequest(BaseModel):
    """Send a student their photos over WhatsApp (W2). ``media_ids=null`` → ALL of the student's
    EFFECTIVE photos; a list → only those (server-intersected with the effective set, so a
    non-effective/rejected id is skipped). Capped (abuse guard → 422)."""

    media_ids: list[str] | None = Field(default=None, max_length=_MAX_SEND_MEDIA_IDS)


class WhatsAppSendResultResponse(BaseModel):
    """One media's outcome from a WhatsApp send (W2)."""

    media_id: str
    status: Literal["sent", "failed", "skipped"]
    reason: str | None = None


class WhatsAppSendResponse(BaseModel):
    """The per-media outcomes of one student-centric WhatsApp send (W2) + the rolled-up counts.
    The FE surfaces an honest toast ("Sent X of N")."""

    results: list[WhatsAppSendResultResponse]
    sent: int
    failed: int
    skipped: int

    @classmethod
    def from_summary(cls, summary: WhatsAppSendSummary) -> WhatsAppSendResponse:
        return cls(
            results=[
                WhatsAppSendResultResponse(
                    media_id=r.media_id, status=r.status, reason=r.reason
                )
                for r in summary.results
            ],
            sent=summary.sent,
            failed=summary.failed,
            skipped=summary.skipped,
        )
