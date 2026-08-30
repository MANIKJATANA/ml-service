"""Per-school WhatsApp config use-cases (W1).

Pure orchestration over the config repo — no HTTP, no RBAC (authorization is at the route),
no image/provider library. The tenant (``school_id``) is the caller's token, passed in by the
route, never a body field. Reads return the school's row or a synthesized "not configured"
default (disabled, all None), so the route always has something to render; the response builder
(``WhatsAppConfigResponse.from_config``) computes the effective/shared-number display. The one
provider secret lives in settings — never touched here.
"""

from __future__ import annotations

from datetime import UTC, datetime

from backend.domain.models import SchoolWhatsAppConfig
from backend.domain.phones import validate_mobile
from backend.domain.ports import WhatsAppConfigRepository


def _clean(value: str | None) -> str | None:
    """Trim an optional string; blank → None."""
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class WhatsAppConfigService:
    def __init__(
        self, repo: WhatsAppConfigRepository, *, default_sender_number: str
    ) -> None:
        self._repo = repo
        self._default_sender_number = default_sender_number

    @property
    def default_sender_number(self) -> str:
        """The shared platform sender a school falls back to (from settings). The route reads
        it to build the response's ``effective_sender_number``."""
        return self._default_sender_number

    async def get_config(self, *, school_id: str) -> SchoolWhatsAppConfig:
        """The school's config, or a synthesized "not configured" default (disabled, all None)
        when the school has never saved one. Tenant from the route."""
        config = await self._repo.get(school_id)
        if config is not None:
            return config
        now = datetime.now(UTC)
        return SchoolWhatsAppConfig(
            school_id=school_id,
            enabled=False,
            sender_number=None,
            template_name=None,
            business_name=None,
            created_at=now,
            updated_at=now,
        )

    async def set_config(
        self,
        *,
        school_id: str,
        enabled: bool,
        sender_number: str | None,
        template_name: str | None,
        business_name: str | None,
    ) -> SchoolWhatsAppConfig:
        """Create/replace the school's config. Trims + blank→None each optional field; the
        sender number is loosely validated via ``domain.phones.validate_mobile`` (a malformed
        one → ``ValidationError`` → 400 — the provider validates authoritatively at send time).
        Tenant from the route, never a body field."""
        sender = validate_mobile(_clean(sender_number))
        return await self._repo.upsert(
            school_id=school_id,
            enabled=enabled,
            sender_number=sender,
            template_name=_clean(template_name),
            business_name=_clean(business_name),
        )
