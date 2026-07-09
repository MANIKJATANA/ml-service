"""School-admin staff routes (decisions/0025).

Tenant isolation: the school is taken from the authenticated user's token, never
from the URL or body — a `school_admin` can only ever manage their own school's
teachers. Requires the `staff:manage` permission.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions
from backend.api.schemas.users import CreateUserRequest, UserResponse
from backend.domain.errors import AuthorizationError
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/staff", tags=["staff"])

# Resolves the caller AND enforces the permission in one dependency.
StaffManager = Annotated[User, Depends(require_permissions(Permission.STAFF_MANAGE))]


def _tenant(user: User) -> str:
    # Non-platform roles always have a school (DB CHECK), but fail closed anyway.
    if user.school_id is None:
        raise AuthorizationError("account is not scoped to a school")
    return user.school_id


@router.post("", status_code=status.HTTP_201_CREATED, response_model=UserResponse)
async def create_teacher(
    body: CreateUserRequest, container: ContainerDep, actor: StaffManager
) -> UserResponse:
    user = await container.onboarding_service().create_teacher(
        school_id=_tenant(actor), email=body.email, password=body.password
    )
    return UserResponse.from_user(user)


@router.get("", response_model=list[UserResponse])
async def list_staff(container: ContainerDep, actor: StaffManager) -> list[UserResponse]:
    staff = await container.onboarding_service().list_staff(school_id=_tenant(actor))
    return [UserResponse.from_user(u) for u in staff]
