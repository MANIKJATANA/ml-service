"""Platform-wide config API schemas (W-live-test).

Platform-admin-facing (``school:manage``). The request is the editable fields; ALL are optional
(``None`` = leave unchanged) so a caller can update just the Meta token OR just the interim
number/mode. The response DELIBERATELY never carries the full ``meta_access_token`` — only a
``token_set`` boolean + a ``token_last4`` hint (the owner-approved masking), so the secret is
never exposed over the wire.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain.models import PlatformConfig

__all__ = [
    "PlatformConfigResponse",
    "UpdatePlatformConfigRequest",
]


class UpdatePlatformConfigRequest(BaseModel):
    """The editable platform config — the three DB-controlled fields (sender number, token,
    interim number). All optional — ``None`` = leave unchanged (a partial update).
    ``meta_access_token`` is the UI-editable Meta temp token (stored in the DB per owner decision;
    never returned in full). ``sender_number`` is the Meta sender phone-number ID."""

    meta_access_token: str | None = Field(default=None, max_length=2000)
    sender_number: str | None = Field(default=None, max_length=64)
    interim_test_number: str | None = Field(default=None, max_length=32)


class PlatformConfigResponse(BaseModel):
    """The platform config, with the Meta token MASKED. ``token_set`` = a token is on file;
    ``token_last4`` = its last 4 chars (a recognition hint), or null. The full token is NEVER
    included. ``sender_number`` (the Meta sender phone-number ID) is NOT a secret and is returned in
    full so the current value is visible. When ``interim_test_number`` is set, every "Send on
    WhatsApp" is diverted to it (the interim test path); clear it for normal delivery."""

    token_set: bool
    token_last4: str | None
    sender_number: str | None
    interim_test_number: str | None
    updated_at: datetime

    @classmethod
    def from_config(cls, config: PlatformConfig) -> PlatformConfigResponse:
        token = config.meta_access_token
        return cls(
            token_set=bool(token),
            token_last4=token[-4:] if token and len(token) >= 4 else None,
            sender_number=config.sender_number,
            interim_test_number=config.interim_test_number,
            updated_at=config.updated_at,
        )
