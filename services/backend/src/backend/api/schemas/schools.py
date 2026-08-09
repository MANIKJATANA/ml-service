"""Schemas for the onboarding routes (decisions/0025)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain.models import School, SchoolStatus
from backend.services.listing_service import SchoolListing
from backend.services.pagination import Page


class CreateSchoolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    max_teachers: int = Field(ge=1, le=100_000)


class UpdateSchoolRequest(BaseModel):
    """Edit a school's mutable fields (BP18c) — all optional; an omitted field is unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    max_teachers: int | None = Field(default=None, ge=1, le=100_000)
    status: SchoolStatus | None = None


class SchoolResponse(BaseModel):
    id: str
    name: str
    max_teachers: int
    status: SchoolStatus
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_school(cls, school: School) -> SchoolResponse:
        return cls(
            id=school.id,
            name=school.name,
            max_teachers=school.max_teachers,
            status=school.status,
            created_at=school.created_at,
            updated_at=school.updated_at,
        )


class SchoolRollupResponse(BaseModel):
    admins: int
    teachers: int
    students: int
    events: int


class SchoolWithRollupResponse(SchoolResponse):
    """A schools list/detail row: the school + its rollup (BP2). ``teachers`` vs
    ``max_teachers`` (inherited) gives capacity used at a glance."""

    rollup: SchoolRollupResponse

    @classmethod
    def from_listing(cls, listing: SchoolListing) -> SchoolWithRollupResponse:
        return cls(
            **SchoolResponse.from_school(listing.school).model_dump(),
            rollup=SchoolRollupResponse(
                admins=listing.rollup.admins,
                teachers=listing.rollup.teachers,
                students=listing.rollup.students,
                events=listing.rollup.events,
            ),
        )


class SchoolListPageResponse(BaseModel):
    """One page of the platform schools list (BP9) + the unpaginated total."""

    items: list[SchoolWithRollupResponse]
    total: int
    limit: int
    offset: int

    @classmethod
    def from_page(cls, page: Page[SchoolListing]) -> SchoolListPageResponse:
        return cls(
            items=[SchoolWithRollupResponse.from_listing(x) for x in page.items],
            total=page.total,
            limit=page.limit,
            offset=page.offset,
        )
