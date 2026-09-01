"""Per-school WhatsApp config API schemas (W1).

School-admin-facing (``whatsapp:manage``). The request is the four editable, NON-SECRET
fields; the response adds the computed display facts — the ``effective_sender_number`` a
school will actually send from (its own, or the shared platform number) and whether it's using
that shared number. The one provider secret is never in either schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from backend.domain.models import SchoolWhatsAppConfig, WhatsAppSendSummary

__all__ = [
    "UpdateWhatsAppConfigRequest",
    "WhatsAppConfigResponse",
    "WhatsAppSendRequest",
    "WhatsAppSendResponse",
    "WhatsAppSendResultResponse",
]

# The most media ids one send request can carry (reuses the students bulk cap → 422 over it).
_MAX_SEND_MEDIA_IDS = 1000


class UpdateWhatsAppConfigRequest(BaseModel):
    """The editable per-school WhatsApp settings (W1). All NON-SECRET."""

    enabled: bool
    sender_number: str | None = Field(default=None, max_length=32)
    template_name: str | None = Field(default=None, max_length=200)
    business_name: str | None = Field(default=None, max_length=200)


class WhatsAppConfigResponse(BaseModel):
    """A school's WhatsApp config + the computed send-from display facts (W1)."""

    school_id: str
    enabled: bool
    sender_number: str | None
    effective_sender_number: str | None
    template_name: str | None
    business_name: str | None
    using_shared_number: bool
    # The active send provider (fake/gupshup/meta) — the FE labels the template field by it
    # (Gupshup: the template UUID; Meta: the template name).
    provider: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_config(
        cls,
        config: SchoolWhatsAppConfig,
        *,
        default_sender_number: str,
        provider: str,
    ) -> WhatsAppConfigResponse:
        return cls(
            school_id=config.school_id,
            enabled=config.enabled,
            sender_number=config.sender_number,
            # The number this school actually sends from: its own, else the shared platform
            # number, else None (nothing configured yet).
            effective_sender_number=config.sender_number
            or default_sender_number
            or None,
            template_name=config.template_name,
            business_name=config.business_name,
            using_shared_number=config.sender_number is None,
            provider=provider,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


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
