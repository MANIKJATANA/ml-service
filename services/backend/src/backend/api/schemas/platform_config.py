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
    """The editable platform config. All optional — ``None`` = leave unchanged (a partial
    update). ``meta_access_token`` is the UI-editable Meta temp token (stored in the DB per
    owner decision; never returned in full)."""

    meta_access_token: str | None = Field(default=None, max_length=2000)
    interim_test_number: str | None = Field(default=None, max_length=32)
    interim_mode: bool | None = None


class PlatformConfigResponse(BaseModel):
    """The platform config, with the Meta token MASKED. ``token_set`` = a token is on file;
    ``token_last4`` = its last 4 chars (a recognition hint), or null. The full token is NEVER
    included."""

    token_set: bool
    token_last4: str | None
    interim_test_number: str | None
    interim_mode: bool
    updated_at: datetime

    @classmethod
    def from_config(cls, config: PlatformConfig) -> PlatformConfigResponse:
        token = config.meta_access_token
        return cls(
            token_set=bool(token),
            token_last4=token[-4:] if token and len(token) >= 4 else None,
            interim_test_number=config.interim_test_number,
            interim_mode=config.interim_mode,
            updated_at=config.updated_at,
        )
