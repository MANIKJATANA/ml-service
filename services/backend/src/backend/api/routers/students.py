"""Student routes — create + ML enrollment (decisions/0026).

Requires the `student:manage` permission (school_admin or teacher). Tenant isolation:
the school is taken from the authenticated user's token (`tenant_of`), never from the
URL or body — a `student_id` from another school resolves to 404. The reference photo
never passes through the backend: the frontend uploads it directly to Supabase via the
signed URL from `POST /v1/students/upload-url`, then submits the object path here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.api.deps import (
    ContainerDep,
    require_permissions,
    resolve_focus_group_ids,
    tenant_of,
)
from backend.api.pagination import (
    DEFAULT_PAGE_SIZE,
    LimitQuery,
    OffsetQuery,
    SearchQuery,
    is_descending,
)
from backend.api.schemas.gallery import DownloadResponse
from backend.api.schemas.students import (
    BulkActionResponse,
    BulkIdsRequest,
    BulkImportRequest,
    BulkImportResponse,
    BulkResendResponse,
    BulkStatusRequest,
    CreateStudentRequest,
    MatchPhotosRequest,
    MatchPhotosResponse,
    ProvisionedStudentResponse,
    SetReferencePhotoRequest,
    StudentEngagementResponse,
    StudentIdsResponse,
    StudentListPageResponse,
    StudentResponse,
    UpdateStudentMobileRequest,
    UpdateStudentRequest,
    UploadUrlResponse,
)
from backend.api.schemas.users import UpdateUserStatusRequest
from backend.domain.models import (
    ActivityFilter,
    EnrollmentStatus,
    MediaVariant,
    SortDir,
    StudentSort,
    User,
)
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/students", tags=["students"])

# Resolves the caller AND enforces the permission in one dependency.
StudentManager = Annotated[User, Depends(require_permissions(Permission.STUDENT_MANAGE))]


@router.post("/upload-url", response_model=UploadUrlResponse)
async def create_upload_url(
    container: ContainerDep, actor: StudentManager
) -> UploadUrlResponse:
    signed = await container.student_service().create_upload_url(
        school_id=tenant_of(actor)
    )
    return UploadUrlResponse.from_signed(
        signed, max_upload_mb=container.settings.max_upload_mb
    )


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ProvisionedStudentResponse
)
async def create_student(
    body: CreateStudentRequest, container: ContainerDep, actor: StudentManager
) -> ProvisionedStudentResponse:
    prov = await container.student_service().create_student(
        school_id=tenant_of(actor),
        name=body.name,
        email=body.email,
        reference_photo_path=body.reference_photo_path,
        mobile_number=body.mobile_number,
        whatsapp_opt_in=body.whatsapp_opt_in,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return ProvisionedStudentResponse.from_provisioned(prov)


@router.post(
    "/bulk", status_code=status.HTTP_201_CREATED, response_model=BulkImportResponse
)
async def bulk_import_students(
    body: BulkImportRequest, container: ContainerDep, actor: StudentManager
) -> BulkImportResponse:
    """Create many students from CSV rows (BP7d) — best-effort, photoless (pending). Each
    created row carries its one-time temp password; the school is the token's."""
    results = await container.student_service().bulk_create_students(
        school_id=tenant_of(actor),
        rows=[
            (r.name, r.email, r.class_name, r.mobile_number) for r in body.students
        ],
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return BulkImportResponse.from_results(results)


@router.post("/match-photos", response_model=MatchPhotosResponse)
async def match_photos(
    body: MatchPhotosRequest, container: ContainerDep, actor: StudentManager
) -> MatchPhotosResponse:
    """Map photo filenames to students for bulk enrollment (BP10) — the FE sends just the
    filenames and gets back which student each maps to (auto-filling an editable table).
    Pure read; tenant from the token; the batch size is capped by the request schema."""
    targets = await container.student_service().resolve_photo_targets(
        school_id=tenant_of(actor), filenames=body.filenames
    )
    return MatchPhotosResponse.from_targets(targets)


@router.delete("/reference-photo-upload", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reference_photo_upload(
    path: Annotated[str, Query(min_length=1, max_length=1024)],
    container: ContainerDep,
    actor: StudentManager,
) -> None:
    """Delete an orphaned bulk-photo upload (BP10) — an object uploaded but never attached to
    a student. Guarded to the caller's own tenant prefix (a foreign path is 400); idempotent.
    Fired best-effort by the FE bulk-photo flow so no orphan is left in storage."""
    await container.student_service().delete_reference_photo_upload(
        school_id=tenant_of(actor), object_path=path
    )


@router.get("", response_model=StudentListPageResponse)
async def list_students(
    container: ContainerDep,
    actor: StudentManager,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    q: SearchQuery = None,
    sort: Annotated[StudentSort, Query()] = StudentSort.NAME,
    dir: Annotated[SortDir, Query()] = SortDir.ASC,
    status: Annotated[EnrollmentStatus | None, Query()] = None,
    student_group_id: Annotated[str | None, Query(max_length=64)] = None,
    mine: Annotated[bool, Query()] = False,
    login: Annotated[ActivityFilter | None, Query()] = None,
    opened: Annotated[ActivityFilter | None, Query()] = None,
) -> StudentListPageResponse:
    """One page of the students list (BP9): server search (name/email), sort (incl. the
    whole-list appearance/event count columns), an enrollment-status filter, and (BP11a) an
    optional class filter (``student_group_id``). BP11c: ``mine=true`` limits a teacher's list
    to the students in their assigned classes (their "focus"); ignored for an admin. BP23:
    ``login=never`` filters to students who never signed in; ``opened=never`` to students who
    never opened a distribution (the "which students?" lists behind the analytics rates)."""
    scope = await resolve_focus_group_ids(container, actor, mine)
    page = await container.listing_service().list_students_page(
        school_id=tenant_of(actor),
        limit=limit,
        offset=offset,
        q=q,
        sort=sort,
        descending=is_descending(dir),
        status=status,
        student_group_id=student_group_id,
        scope_group_ids=scope,
        never_signed_in=login is ActivityFilter.NEVER,
        never_opened=opened is ActivityFilter.NEVER,
    )
    return StudentListPageResponse.from_page(page)


@router.get("/ids", response_model=StudentIdsResponse)
async def list_student_ids(
    container: ContainerDep,
    actor: StudentManager,
    q: SearchQuery = None,
    status: Annotated[EnrollmentStatus | None, Query()] = None,
    student_group_id: Annotated[str | None, Query(max_length=64)] = None,
    mine: Annotated[bool, Query()] = False,
    login: Annotated[ActivityFilter | None, Query()] = None,
    opened: Annotated[ActivityFilter | None, Query()] = None,
) -> StudentIdsResponse:
    """Every student id matching the given filter (BP27 select-all-matching) — so a bulk
    enable/disable/delete can span every page, not just the loaded one. Takes the SAME filter
    params as ``GET /v1/students`` (minus sort/pagination), so the id set is identical to what
    the list shows. Tenant from the token; a teacher's ``mine=true`` focus is honored. Registered
    before ``/{student_id}`` so the literal wins the route match."""
    scope = await resolve_focus_group_ids(container, actor, mine)
    scan = await container.listing_service().list_student_ids(
        school_id=tenant_of(actor),
        q=q,
        status=status,
        student_group_id=student_group_id,
        scope_group_ids=scope,
        never_signed_in=login is ActivityFilter.NEVER,
        never_opened=opened is ActivityFilter.NEVER,
    )
    return StudentIdsResponse.from_scan(scan)


@router.post("/bulk-status", response_model=BulkActionResponse)
async def bulk_set_student_status(
    body: BulkStatusRequest, container: ContainerDep, actor: StudentManager
) -> BulkActionResponse:
    """Enable/disable many students' logins at once (BP27) — best-effort per id (a foreign/
    missing id is recorded ``error`` and the batch continues). Tenant from the token; registered
    before ``/{student_id}`` so the literal wins the route match."""
    results = await container.student_service().bulk_set_status(
        school_id=tenant_of(actor),
        student_ids=body.student_ids,
        status=body.status,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return BulkActionResponse.from_results(results)


@router.post("/bulk-delete", response_model=BulkActionResponse)
async def bulk_delete_students(
    body: BulkIdsRequest, container: ContainerDep, actor: StudentManager
) -> BulkActionResponse:
    """Erase many students at once (BP27) — best-effort per id (an ML-down 502 or a foreign/
    missing id is recorded ``error`` and the batch continues; the ML DELETE is idempotent, so a
    retried ``error`` row self-heals). Tenant from the token; registered before ``/{student_id}``
    so the literal wins the route match."""
    results = await container.student_service().bulk_delete_students(
        school_id=tenant_of(actor),
        student_ids=body.student_ids,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return BulkActionResponse.from_results(results)


@router.post("/bulk-resend-invite", response_model=BulkResendResponse)
async def bulk_resend_student_invites(
    body: BulkIdsRequest, container: ContainerDep, actor: StudentManager
) -> BulkResendResponse:
    """Re-issue a fresh one-time temp password for many students at once (BP27b) — best-effort per
    id (a foreign/missing id is recorded ``error`` and the batch continues). The response carries
    each ``sent`` row's ONE-TIME temp password (shown once so staff can hand them out; never
    returned again — only the hashes are stored). Recovery without the destructive delete: each
    student's photos + matches are untouched. Tenant from the token; registered before
    ``/{student_id}`` so the literal wins the route match."""
    results = await container.student_service().bulk_resend_invite(
        school_id=tenant_of(actor),
        student_ids=body.student_ids,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return BulkResendResponse.from_results(results)


@router.post("/bulk-remove-class", response_model=BulkActionResponse)
async def bulk_remove_students_from_class(
    body: BulkIdsRequest, container: ContainerDep, actor: StudentManager
) -> BulkActionResponse:
    """Remove many students from their class at once (BP27c / R4-A10) — best-effort per id (a
    foreign/missing id is recorded ``error`` and the batch continues). Clears each student's class
    pointer (``student_group_id → null``); never deletes the student or the class. Tenant from the
    token; registered before ``/{student_id}`` so the literal wins the route match."""
    results = await container.class_service().remove_students_bulk(
        school_id=tenant_of(actor), student_ids=body.student_ids
    )
    return BulkActionResponse.from_results(results)


@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> StudentResponse:
    student = await container.student_service().get_student(
        school_id=tenant_of(actor), student_id=student_id
    )
    return StudentResponse.from_student(student)


@router.patch("/{student_id}", response_model=StudentResponse)
async def update_student(
    student_id: str,
    body: UpdateStudentRequest,
    container: ContainerDep,
    actor: StudentManager,
) -> StudentResponse:
    """Set (or clear) a student's class (BP11a). Tenant from the token; a foreign student or
    a foreign target class → 404."""
    student = await container.class_service().set_student_group(
        school_id=tenant_of(actor),
        student_id=student_id,
        group_id=body.student_group_id,
    )
    return StudentResponse.from_student(student)


@router.get("/{student_id}/engagement", response_model=StudentEngagementResponse)
async def student_engagement(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> StudentEngagementResponse:
    """One student's reach + engagement (BP23) — events/photos they appear in, how many
    they've opened + last-open, and their own downloads. Tenant from the token (a foreign
    student → 404); a separate read so the write-path StudentResponse stays lean."""
    engagement = await container.engagement_service().student_engagement(
        school_id=tenant_of(actor), student_id=student_id
    )
    return StudentEngagementResponse.from_engagement(engagement)


@router.get("/{student_id}/reference-photo", response_model=DownloadResponse)
async def student_reference_photo(
    student_id: str,
    container: ContainerDep,
    actor: StudentManager,
    size: Annotated[MediaVariant, Query()] = MediaVariant.THUMB,
) -> DownloadResponse:
    """A short-lived signed URL for a student's reference photo — the staff-list/detail
    avatar (BP17). Thumbnail by default; `?size=full` for a crisper detail header. 404 if
    the student is photoless or belongs to another school."""
    signed = await container.student_service().reference_photo_url(
        school_id=tenant_of(actor),
        student_id=student_id,
        thumbnail=(size is MediaVariant.THUMB),
    )
    return DownloadResponse.from_signed(signed)


@router.post("/{student_id}/enroll", response_model=StudentResponse)
async def enroll_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> StudentResponse:
    student = await container.student_service().enroll_student(
        school_id=tenant_of(actor),
        student_id=student_id,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return StudentResponse.from_student(student)


@router.post("/{student_id}/resend-invite", response_model=ProvisionedStudentResponse)
async def resend_student_invite(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> ProvisionedStudentResponse:
    """Re-issue a one-time temp password for a student who lost theirs (BP18a). Tenant from
    the token (a foreign student → 404); regenerates + forces a change on next login and
    returns it once. Does NOT delete/re-create — the student's photos + matches are kept."""
    prov = await container.student_service().resend_invite(
        school_id=tenant_of(actor),
        student_id=student_id,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return ProvisionedStudentResponse.from_provisioned(prov)


@router.patch("/{student_id}/status", response_model=StudentResponse)
async def set_student_status(
    student_id: str,
    body: UpdateUserStatusRequest,
    container: ContainerDep,
    actor: StudentManager,
) -> StudentResponse:
    """Enable/disable a student's login (BP18d) — a non-destructive kill-switch. Tenant from
    the token (a foreign student → 404); a disabled student can't sign in but keeps every
    photo + match row (unlike delete). Idempotent."""
    student = await container.student_service().set_status(
        school_id=tenant_of(actor),
        student_id=student_id,
        status=body.status,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return StudentResponse.from_student(student)


@router.patch("/{student_id}/mobile", response_model=StudentResponse)
async def set_student_mobile(
    student_id: str,
    body: UpdateStudentMobileRequest,
    container: ContainerDep,
    actor: StudentManager,
) -> StudentResponse:
    """Set/clear a student's WhatsApp contact number + opt-in (Phase 0). Tenant from the token
    (a foreign student → 404); a malformed number → 400. Touches no photo / enrollment / match
    data. No admin-action audit — a contact/consent edit isn't a governance action."""
    student = await container.student_service().set_mobile(
        school_id=tenant_of(actor),
        student_id=student_id,
        mobile_number=body.mobile_number,
        whatsapp_opt_in=body.whatsapp_opt_in,
    )
    return StudentResponse.from_student(student)


@router.put("/{student_id}/reference-photo", response_model=StudentResponse)
async def set_reference_photo(
    student_id: str,
    body: SetReferencePhotoRequest,
    container: ContainerDep,
    actor: StudentManager,
) -> StudentResponse:
    """Set/replace the student's reference photo, then (re-)enroll (BP7d-2). Tenant from
    the token; the path must be under this school's upload prefix."""
    student = await container.student_service().set_reference_photo(
        school_id=tenant_of(actor),
        student_id=student_id,
        reference_photo_path=body.reference_photo_path,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return StudentResponse.from_student(student)


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> None:
    await container.student_service().delete_student(
        school_id=tenant_of(actor),
        student_id=student_id,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
