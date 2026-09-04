"""Platform-wide config routes (W-live-test).

Platform-admin only (``school:manage`` — the platform admin's one permission). Two endpoints:
read the platform config (Meta token MASKED — only ``token_set``/``token_last4``), and
create/replace it (a partial update, so ``None`` fields are left unchanged). The full Meta token
NEVER transits these routes on the way out; a school admin / teacher / student is 403.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import ContainerDep, require_permissions
from backend.api.schemas.platform_config import (
    PlatformConfigResponse,
    UpdatePlatformConfigRequest,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/platform/whatsapp-config", tags=["platform"])

PlatformAdmin = Annotated[
    User, Depends(require_permissions(Permission.SCHOOL_MANAGE))
]


@router.get("", response_model=PlatformConfigResponse)
async def get_platform_config(
    container: ContainerDep, actor: PlatformAdmin
) -> PlatformConfigResponse:
    """The platform config (a synthesized empty default if never saved). The Meta token is
    masked — only ``token_set``/``token_last4`` are returned."""
    config = await container.platform_config_service().get_config()
    return PlatformConfigResponse.from_config(config)


@router.put("", response_model=PlatformConfigResponse)
async def update_platform_config(
    body: UpdatePlatformConfigRequest,
    container: ContainerDep,
    actor: PlatformAdmin,
) -> PlatformConfigResponse:
    """Create/replace the platform config (a partial update — ``None`` fields are left
    unchanged). The response masks the Meta token."""
    config = await container.platform_config_service().set_config(
        meta_access_token=body.meta_access_token,
        sender_number=body.sender_number,
        template_name=body.template_name,
        interim_test_number=body.interim_test_number,
    )
    return PlatformConfigResponse.from_config(config)
