"""Platform onboarding routes: schools + their admins (decisions/0025).

Platform-only — the whole router requires the `school:manage` permission, so a
`platform_admin` operates across tenants and `school_id` is a path parameter here
(unlike the school-scoped staff routes, which derive it from the token).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from backend.api.deps import ContainerDep, require_permissions
from backend.api.pagination import (
    DEFAULT_PAGE_SIZE,
    LimitQuery,
    OffsetQuery,
    SearchQuery,
    is_descending,
)
from backend.api.schemas.schools import (
    CreateSchoolRequest,
    SchoolListPageResponse,
    SchoolResponse,
    SchoolWithRollupResponse,
    UpdateSchoolRequest,
)
from backend.api.schemas.users import (
    CreateUserRequest,
    ProvisionedUserResponse,
    UpdateUserStatusRequest,
    UserListPageResponse,
    UserResponse,
)
from backend.domain.models import Role, SchoolSort, SortDir, User, UserSort
from backend.domain.permissions import Permission

router = APIRouter(
    prefix="/v1/schools",
    tags=["schools"],
    dependencies=[Depends(require_permissions(Permission.SCHOOL_MANAGE))],
)

# The router already gates SCHOOL_MANAGE, so these handlers didn't resolve the caller. BP28b
# needs the actor for the governance audit — this alias re-declares the (already-enforced) gate
# purely to inject the platform admin. NB: for these routes the audit row's ``school_id`` is the
# URL ``school_id`` (the target school), so that school's admin reads it via ``audit:view``.
PlatformAdmin = Annotated[User, Depends(require_permissions(Permission.SCHOOL_MANAGE))]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SchoolResponse)
async def create_school(
    body: CreateSchoolRequest, container: ContainerDep
) -> SchoolResponse:
    school = await container.onboarding_service().create_school(
        name=body.name, max_teachers=body.max_teachers
    )
    return SchoolResponse.from_school(school)


@router.get("", response_model=SchoolListPageResponse)
async def list_schools(
    container: ContainerDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    q: SearchQuery = None,
    sort: Annotated[SchoolSort, Query()] = SchoolSort.NAME,
    dir: Annotated[SortDir, Query()] = SortDir.ASC,
) -> SchoolListPageResponse:
    """One page of the platform schools list (BP9): server search (name) + sort (incl. the
    whole-list students/events/teachers/admins rollup columns)."""
    page = await container.listing_service().list_schools_page(
        limit=limit, offset=offset, q=q, sort=sort, descending=is_descending(dir)
    )
    return SchoolListPageResponse.from_page(page)


@router.get("/{school_id}", response_model=SchoolWithRollupResponse)
async def get_school(
    school_id: str, container: ContainerDep
) -> SchoolWithRollupResponse:
    listing = await container.listing_service().get_school(school_id=school_id)
    return SchoolWithRollupResponse.from_listing(listing)


@router.patch("/{school_id}", response_model=SchoolResponse)
async def update_school(
    school_id: str,
    body: UpdateSchoolRequest,
    container: ContainerDep,
    actor: PlatformAdmin,
) -> SchoolResponse:
    """Rename a school, change its teacher cap, or suspend/reactivate it (BP18c). Only the
    provided fields change; an unknown school -> 404. Platform-only (the router gate)."""
    school = await container.onboarding_service().update_school(
        school_id=school_id,
        name=body.name,
        max_teachers=body.max_teachers,
        status=body.status,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return SchoolResponse.from_school(school)


@router.get("/{school_id}/admins", response_model=UserListPageResponse)
async def list_school_admins(
    school_id: str,
    container: ContainerDep,
    limit: LimitQuery = DEFAULT_PAGE_SIZE,
    offset: OffsetQuery = 0,
    q: SearchQuery = None,
    sort: Annotated[UserSort, Query()] = UserSort.CREATED_AT,
    dir: Annotated[SortDir, Query()] = SortDir.DESC,
) -> UserListPageResponse:
    """One page of the school's administrator roster (BP9). Add-admin is the existing POST."""
    page = await container.listing_service().list_school_admins_page(
        school_id=school_id,
        limit=limit,
        offset=offset,
        q=q,
        sort=sort,
        descending=is_descending(dir),
    )
    return UserListPageResponse.from_page(page)


@router.post(
    "/{school_id}/admins",
    status_code=status.HTTP_201_CREATED,
    response_model=ProvisionedUserResponse,
)
async def create_school_admin(
    school_id: str,
    body: CreateUserRequest,
    container: ContainerDep,
    actor: PlatformAdmin,
) -> ProvisionedUserResponse:
    provisioned = await container.onboarding_service().create_school_admin(
        school_id=school_id,
        email=body.email,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return ProvisionedUserResponse.from_provisioned(provisioned)


@router.patch("/{school_id}/admins/{user_id}", response_model=UserResponse)
async def set_admin_status(
    school_id: str,
    user_id: str,
    body: UpdateUserStatusRequest,
    container: ContainerDep,
    actor: PlatformAdmin,
) -> UserResponse:
    """Enable/disable a school admin (platform). A non-admin/other-school id -> 404."""
    user = await container.onboarding_service().set_staff_status(
        school_id=school_id,
        user_id=user_id,
        role=Role.SCHOOL_ADMIN,
        status=body.status,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return UserResponse.from_user(user)


@router.post(
    "/{school_id}/admins/{user_id}/resend-invite",
    response_model=ProvisionedUserResponse,
)
async def resend_admin_invite(
    school_id: str, user_id: str, container: ContainerDep, actor: PlatformAdmin
) -> ProvisionedUserResponse:
    """Re-issue a one-time temp password for a school admin (BP7c)."""
    provisioned = await container.onboarding_service().resend_invite(
        school_id=school_id,
        user_id=user_id,
        role=Role.SCHOOL_ADMIN,
        actor_user_id=actor.id,
        actor_role=actor.role.value,
    )
    return ProvisionedUserResponse.from_provisioned(provisioned)
