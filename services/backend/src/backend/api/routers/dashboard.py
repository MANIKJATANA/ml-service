"""Admin dashboard route (BP1, decisions/0038).

The school command center: one read returning student/event/photo rollups + the
needs-attention signals. Gated on ``dashboard:view`` (school_admin + teacher). Tenant is
the caller's token ``school_id`` (`tenant_of`), never the URL — a caller only ever sees
their own school's numbers. Platform admins have no token school and don't reach here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.dashboard import DashboardResponse
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1", tags=["dashboard"])

DashboardViewer = Annotated[
    User, Depends(require_permissions(Permission.DASHBOARD_VIEW))
]


@router.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard(
    container: ContainerDep, actor: DashboardViewer
) -> DashboardResponse:
    summary = await container.dashboard_service().school_summary(
        school_id=tenant_of(actor)
    )
    return DashboardResponse.from_dashboard(summary)
