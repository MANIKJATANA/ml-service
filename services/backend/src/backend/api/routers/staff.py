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
from backend.api.schemas.users import (
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
