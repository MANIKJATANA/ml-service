"""Access/download audit routes (BP8b, decisions/0050).

School-admin-only (``audit:view``, admin-only for now — a one-line grant adds teachers
later). Two reads: a per-photo download history and a paginated, filterable school-wide log.
Tenant is the token's (``tenant_of``), never the URL — a foreign media id resolves to 404 and
a foreign log row never appears (the repo filters by ``school_id``). Downloads are recorded
by ``GalleryService`` on the download path; this router only reads them.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.pagination import DEFAULT_PAGE_SIZE, LimitQuery, OffsetQuery
from backend.api.schemas.audit import (
    DownloadLogPageResponse,
    MediaDownloadLogResponse,
)
from backend.domain.models import User
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
) -> DownloadLogPageResponse:
    page = await container.audit_service().school_download_log(
        school_id=tenant_of(actor),
        limit=limit,
        offset=offset,
        event_id=event_id,
        student_id=student_id,
    )
    return DownloadLogPageResponse.from_page(page)
