"""School-admin staff routes (decisions/0025).

Tenant isolation: the school is taken from the authenticated user's token, never
from the URL or body — a `school_admin` can only ever manage their own school's
teachers. Requires the `staff:manage` permission.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.pagination import (
    DEFAULT_PAGE_SIZE,
    LimitQuery,
    OffsetQuery,
    SearchQuery,
    is_descending,
)
from backend.api.schemas.classes import (
    ClassRefListResponse,
    SetTeacherClassesRequest,
)
from backend.api.schemas.users import (
    BulkStaffRequest,
    BulkStaffResponse,
    CreateUserRequest,
    ProvisionedUserResponse,
    UpdateUserStatusRequest,
    UserListPageResponse,
    UserResponse,
)
from backend.domain.models import Role, SortDir, User, UserSort
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/staff", tags=["staff"])

# Resolves the caller AND enforces the permission in one dependency.
StaffManager = Annotated[User, Depends(require_permissions(Permission.STAFF_MANAGE))]
# Teacher↔class delegation reuses class:manage (admin-only, like BP11a class lifecycle).
ClassManager = Annotated[User, Depends(require_permissions(Permission.CLASS_MANAGE))]

# The shared tenant-from-token helper (one implementation, decisions/0026). Kept
# under this name so existing imports (tests) still resolve.
_tenant = tenant_of


@router.post(
    "", status_code=status.HTTP_201_CREATED, response_model=ProvisionedUserResponse
)
async def create_teacher(
    body: CreateUserRequest, container: ContainerDep, actor: StaffManager
) -> ProvisionedUserResponse:
    provisioned = await container.onboarding_service().create_teacher(
        school_id=_tenant(actor), email=body.email
    )
    return ProvisionedUserResponse.from_provisioned(provisioned)


@router.post(
    "/bulk", status_code=status.HTTP_201_CREATED, response_model=BulkStaffResponse
)
async def bulk_create_staff(
    body: BulkStaffRequest, container: ContainerDep, actor: StaffManager
) -> BulkStaffResponse:
    """Invite many teachers from a list of emails at once (BP27b) — best-effort per row (a
    malformed email → ``invalid``, a duplicate → ``duplicate``, the cap → ``limit_reached``; the
    batch never aborts). The response carries each ``created`` row's ONE-TIME temp password (shown
    once so the admin can hand them out; never returned again — only the hashes are stored).
    school_admin-only (``staff:manage``); the school is the token's, never the body. Registered
    before ``/{user_id}`` so the literal wins the route match."""
    results = await container.onboarding_service().bulk_create_staff(
        school_id=_tenant(actor), emails=body.emails
    )
    return BulkStaffResponse.from_results(results)


@router.get("", response_model=UserListPageResponse)
async def list_staff(
    container: ContainerDep,
    actor: StaffManager,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    q: SearchQuery = None,
    sort: Annotated[UserSort, Query()] = UserSort.CREATED_AT,
    dir: Annotated[SortDir, Query()] = SortDir.DESC,
) -> UserListPageResponse:
    """One page of the teacher roster (BP9): server search (email) + email/created sort."""
    page = await container.onboarding_service().list_staff_page(
        school_id=_tenant(actor),
        limit=limit,
        offset=offset,
        q=q,
        sort=sort,
        descending=is_descending(dir),
    )
    return UserListPageResponse.from_page(page)


@router.patch("/{user_id}", response_model=UserResponse)
async def set_teacher_status(
    user_id: str,
    body: UpdateUserStatusRequest,
    container: ContainerDep,
    actor: StaffManager,
) -> UserResponse:
    """Enable/disable a teacher. Tenant from the token; a foreign/non-teacher id -> 404."""
    user = await container.onboarding_service().set_staff_status(
        school_id=_tenant(actor), user_id=user_id, role=Role.TEACHER, status=body.status
    )
    return UserResponse.from_user(user)


@router.post("/{user_id}/resend-invite", response_model=ProvisionedUserResponse)
async def resend_teacher_invite(
    user_id: str, container: ContainerDep, actor: StaffManager
) -> ProvisionedUserResponse:
    """Re-issue a one-time temp password for a teacher (BP7c)."""
    provisioned = await container.onboarding_service().resend_invite(
        school_id=_tenant(actor), user_id=user_id, role=Role.TEACHER
    )
    return ProvisionedUserResponse.from_provisioned(provisioned)


# ---- BP11c teacher delegation: a teacher's classes (admin-only) ----------


@router.get("/{user_id}/classes", response_model=ClassRefListResponse)
async def list_teacher_classes(
    user_id: str, container: ContainerDep, actor: ClassManager
) -> ClassRefListResponse:
    """The classes this teacher is assigned to (BP11c — the staff-row chip). Tenant from the
    token; a foreign/non-teacher id → 404."""
    groups = await container.delegation_service().list_teacher_classes(
        school_id=_tenant(actor), teacher_id=user_id
    )
    return ClassRefListResponse.from_groups(groups)


@router.put("/{user_id}/classes", response_model=ClassRefListResponse)
async def set_teacher_classes(
    user_id: str,
    body: SetTeacherClassesRequest,
    container: ContainerDep,
    actor: ClassManager,
) -> ClassRefListResponse:
    """Replace a teacher's whole class set (BP11c — the "Edit classes" dialog). Tenant from the
    token; a foreign/non-teacher id → 404, a foreign class id is silently skipped."""
    groups = await container.delegation_service().set_teacher_classes(
        school_id=_tenant(actor), teacher_id=user_id, group_ids=body.group_ids
    )
    return ClassRefListResponse.from_groups(groups)
