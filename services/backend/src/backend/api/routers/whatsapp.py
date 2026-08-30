"""Per-school WhatsApp config routes (W1).

School-admin-only (``whatsapp:manage``). Two endpoints: read the school's config, and
create/replace it. Tenant is the token's (``tenant_of``), never the URL or body — a school
only ever sees/edits its own config. The one provider secret is a process env var; nothing
secret transits these routes. W1 configures but SENDS NOTHING — there is no send endpoint here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.whatsapp import (
    UpdateWhatsAppConfigRequest,
    WhatsAppConfigResponse,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/schools/whatsapp-config", tags=["whatsapp"])

WhatsAppManager = Annotated[
    User, Depends(require_permissions(Permission.WHATSAPP_MANAGE))
]


@router.get("", response_model=WhatsAppConfigResponse)
async def get_whatsapp_config(
    container: ContainerDep, actor: WhatsAppManager
) -> WhatsAppConfigResponse:
    """The school's WhatsApp config (a synthesized disabled default if never saved)."""
    service = container.whatsapp_config_service()
    config = await service.get_config(school_id=tenant_of(actor))
    return WhatsAppConfigResponse.from_config(
        config, default_sender_number=service.default_sender_number
    )


@router.put("", response_model=WhatsAppConfigResponse)
async def update_whatsapp_config(
    body: UpdateWhatsAppConfigRequest,
    container: ContainerDep,
    actor: WhatsAppManager,
) -> WhatsAppConfigResponse:
    """Create/replace the school's WhatsApp config. Tenant from the token. W1 saves settings
    only — it does not send anything (that is W2)."""
    service = container.whatsapp_config_service()
    config = await service.set_config(
        school_id=tenant_of(actor),
        enabled=body.enabled,
        sender_number=body.sender_number,
        template_name=body.template_name,
        business_name=body.business_name,
    )
    return WhatsAppConfigResponse.from_config(
        config, default_sender_number=service.default_sender_number
    )
