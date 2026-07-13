"""Platform onboarding routes: schools + their admins (decisions/0025).

Platform-only — the whole router requires the `school:manage` permission, so a
`platform_admin` operates across tenants and `school_id` is a path parameter here
(unlike the school-scoped staff routes, which derive it from the token).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions
from backend.api.schemas.schools import (
    CreateSchoolRequest,
    SchoolResponse,
    SchoolWithRollupResponse,
)
from backend.api.schemas.users import CreateUserRequest, UserResponse
from backend.domain.permissions import Permission

router = APIRouter(
    prefix="/v1/schools",
    tags=["schools"],
    dependencies=[Depends(require_permissions(Permission.SCHOOL_MANAGE))],
)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=SchoolResponse)
async def create_school(
    body: CreateSchoolRequest, container: ContainerDep
) -> SchoolResponse:
    school = await container.onboarding_service().create_school(
        name=body.name, max_teachers=body.max_teachers
    )
    return SchoolResponse.from_school(school)


@router.get("", response_model=list[SchoolWithRollupResponse])
async def list_schools(container: ContainerDep) -> list[SchoolWithRollupResponse]:
    listings = await container.listing_service().list_schools()
    return [SchoolWithRollupResponse.from_listing(x) for x in listings]


@router.get("/{school_id}", response_model=SchoolWithRollupResponse)
async def get_school(
    school_id: str, container: ContainerDep
) -> SchoolWithRollupResponse:
    listing = await container.listing_service().get_school(school_id=school_id)
    return SchoolWithRollupResponse.from_listing(listing)


@router.get("/{school_id}/admins", response_model=list[UserResponse])
async def list_school_admins(
    school_id: str, container: ContainerDep
) -> list[UserResponse]:
    """The school's administrator roster (BP2). Add-admin is the existing POST."""
    admins = await container.listing_service().list_school_admins(school_id=school_id)
    return [UserResponse.from_user(u) for u in admins]


@router.post(
    "/{school_id}/admins",
    status_code=status.HTTP_201_CREATED,
    response_model=UserResponse,
)
async def create_school_admin(
    school_id: str, body: CreateUserRequest, container: ContainerDep
) -> UserResponse:
    user = await container.onboarding_service().create_school_admin(
        school_id=school_id, email=body.email, password=body.password
    )
    return UserResponse.from_user(user)
