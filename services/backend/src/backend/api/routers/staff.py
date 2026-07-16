"""School-admin staff routes (decisions/0025).

Tenant isolation: the school is taken from the authenticated user's token, never
from the URL or body — a `school_admin` can only ever manage their own school's
teachers. Requires the `staff:manage` permission.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.users import (
    CreateUserRequest,
    ProvisionedUserResponse,
    UpdateUserStatusRequest,
    UserResponse,
)
from backend.domain.models import Role, User
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


@router.get("", response_model=list[UserResponse])
async def list_staff(container: ContainerDep, actor: StaffManager) -> list[UserResponse]:
    staff = await container.onboarding_service().list_staff(school_id=_tenant(actor))
    return [UserResponse.from_user(u) for u in staff]


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
