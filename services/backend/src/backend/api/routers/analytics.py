"""Program analytics routes (BP14, decisions/0062).

Two read endpoints:

- ``GET /v1/analytics/school`` — the school program view (rates + per-term + trend). Gated
  ``dashboard:view`` (school_admin + teacher); tenant is the caller's token ``school_id``
  (`tenant_of`), never the URL. Platform admins have no token school and don't reach here.
- ``GET /v1/analytics/estate`` — the platform adoption view (per-school funnel + stalled
  flags). Gated ``school:manage`` (platform admin), cross-tenant by design.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.analytics import (
    EstateAnalyticsResponse,
    SchoolAnalyticsResponse,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/analytics", tags=["analytics"])

SchoolViewer = Annotated[
    User, Depends(require_permissions(Permission.DASHBOARD_VIEW))
]
EstateViewer = Annotated[
    User, Depends(require_permissions(Permission.SCHOOL_MANAGE))
]


@router.get("/school", response_model=SchoolAnalyticsResponse)
async def get_school_analytics(
    container: ContainerDep, actor: SchoolViewer
) -> SchoolAnalyticsResponse:
    analytics = await container.analytics_service().school_analytics(
        school_id=tenant_of(actor)
    )
    return SchoolAnalyticsResponse.from_analytics(analytics)


@router.get("/estate", response_model=EstateAnalyticsResponse)
async def get_estate_analytics(
    container: ContainerDep, _actor: EstateViewer
) -> EstateAnalyticsResponse:
    analytics = await container.analytics_service().estate_analytics()
    return EstateAnalyticsResponse.from_analytics(analytics)
