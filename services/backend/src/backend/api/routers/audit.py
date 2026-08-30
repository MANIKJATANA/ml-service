"""Access/download audit routes (BP8b, decisions/0050).

School-admin-only (``audit:view``, admin-only for now — a one-line grant adds teachers
later). Two reads: a per-photo download history and a paginated, filterable school-wide log.
Tenant is the token's (``tenant_of``), never the URL — a foreign media id resolves to 404 and
a foreign log row never appears (the repo filters by ``school_id``). Downloads are recorded
by ``GalleryService`` on the download path; this router only reads them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.pagination import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery
from backend.api.schemas.audit import (
    AdminActionLogPageResponse,
    DownloadLogPageResponse,
    MediaDownloadLogResponse,
)
from backend.domain.models import AdminAction, AdminActionTargetType, Role, User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1", tags=["audit"])

AuditViewer = Annotated[User, Depends(require_permissions(Permission.AUDIT_VIEW))]


@router.get("/media/{media_id}/download-log", response_model=MediaDownloadLogResponse)
async def media_download_log(
    media_id: str, container: ContainerDep, actor: AuditViewer
) -> MediaDownloadLogResponse:
    history = await container.audit_service().media_download_history(
        school_id=tenant_of(actor), media_id=media_id
    )
    return MediaDownloadLogResponse.from_view(history)


@router.get("/audit/downloads", response_model=DownloadLogPageResponse)
async def download_log(
    container: ContainerDep,
    actor: AuditViewer,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    event_id: Annotated[str | None, Query()] = None,
    student_id: Annotated[str | None, Query()] = None,
    # BP28a: typed at the boundary so a malformed value 422s here — a bad date (created_from/to)
    # or an unknown role never reaches the service.
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
    actor_role: Annotated[Role | None, Query()] = None,
) -> DownloadLogPageResponse:
    page = await container.audit_service().school_download_log(
        school_id=tenant_of(actor),
        limit=limit,
        offset=offset,
        event_id=event_id,
        student_id=student_id,
        created_from=created_from,
        created_to=created_to,
        actor_role=actor_role.value if actor_role else None,
    )
    return DownloadLogPageResponse.from_page(page)


@router.get("/audit/actions", response_model=AdminActionLogPageResponse)
async def admin_action_log(
    container: ContainerDep,
    actor: AuditViewer,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    # Typed enums at the boundary → a bad action/target_type 422s here, never reaching the
    # service; a bad date on the range likewise. The target/actor id filters stay free-form.
    action: Annotated[AdminAction | None, Query()] = None,
    target_type: Annotated[AdminActionTargetType | None, Query()] = None,
    target_id: Annotated[str | None, Query()] = None,
    actor_user_id: Annotated[str | None, Query()] = None,
    created_from: Annotated[datetime | None, Query()] = None,
    created_to: Annotated[datetime | None, Query()] = None,
) -> AdminActionLogPageResponse:
    """The school-wide admin-action audit — who did each governance action (BP28b), newest-
    first. Same ``audit:view`` gate as the download log (school_admin only); tenant strictly
    from the token."""
    page = await container.admin_action_audit_service().school_action_log(
        school_id=tenant_of(actor),
        limit=limit,
        offset=offset,
        action=action.value if action else None,
        target_type=target_type.value if target_type else None,
        target_id=target_id,
        actor_user_id=actor_user_id,
        created_from=created_from,
        created_to=created_to,
    )
    return AdminActionLogPageResponse.from_page(page)
