"""WhatsApp send API schemas (W2).

Staff-facing (``whatsapp:send``). Schools no longer configure WhatsApp — the per-school config
request/response were removed in 0099 (the platform admin owns it all; see
``api/schemas/platform_config.py``). This module now holds only the send request + per-media
results.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from backend.domain.models import EventPhotoSendSummary, WhatsAppSendSummary

__all__ = [
    "EventPhotoRecipientResponse",
    "EventPhotoRecipientsRequest",
    "EventPhotoRecipientsResponse",
    "EventPhotoSendRequest",
    "EventPhotoSendResponse",
    "EventPhotoSendResultResponse",
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


# ---- event-photo fan-out ("send selected photos to whoever appears") ----


class EventPhotoRecipientsRequest(BaseModel):
    """The SELECTED event photos to preview recipients for. Capped (abuse guard → 422)."""

    media_ids: list[str] = Field(min_length=1, max_length=_MAX_SEND_MEDIA_IDS)


class EventPhotoRecipientResponse(BaseModel):
    """One student who effectively appears in the selected photos + how many they're in, and
    whether they can receive (opted in + a number). NON-SECRET, no recipient number."""

    student_id: str
    name: str
    photo_count: int
    opted_in: bool
    has_number: bool


class EventPhotoRecipientsResponse(BaseModel):
    """The pre-send preview: who would receive what if you fan the selected photos out. The FE
    shows "N students · X messages · M skipped" so the user confirms before any send. ``interim``
    is the platform WhatsApp test mode (an interim test number is set) — while on, EVERY appearing
    student's photos go to the test number regardless of consent, so the FE lets the send proceed
    even if no student is opted-in (the server is authoritative)."""

    recipients: list[EventPhotoRecipientResponse]
    interim: bool


class EventPhotoSendRequest(BaseModel):
    """The SELECTED event photos to fan out to whoever appears in them. Capped (→ 422)."""

    media_ids: list[str] = Field(min_length=1, max_length=_MAX_SEND_MEDIA_IDS)


class EventPhotoSendResultResponse(BaseModel):
    """One student's outcome from an event-photo fan-out. ``reason`` is set only when the whole
    student was skipped (not opted in / no number)."""

    student_id: str
    name: str
    sent: int
    failed: int
    skipped: int
    reason: str | None = None


class EventPhotoSendResponse(BaseModel):
    """The rolled-up outcome of an event-photo fan-out (per-student + totals). PII-free."""

    results: list[EventPhotoSendResultResponse]
    students_sent: int
    students_skipped: int
    sent: int
    failed: int
    skipped: int

    @classmethod
    def from_summary(cls, summary: EventPhotoSendSummary) -> EventPhotoSendResponse:
        return cls(
            results=[
                EventPhotoSendResultResponse(
                    student_id=r.student_id,
                    name=r.name,
                    sent=r.sent,
                    failed=r.failed,
                    skipped=r.skipped,
                    reason=r.reason,
                )
                for r in summary.results
            ],
            students_sent=summary.students_sent,
            students_skipped=summary.students_skipped,
            sent=summary.sent,
            failed=summary.failed,
            skipped=summary.skipped,
        )
