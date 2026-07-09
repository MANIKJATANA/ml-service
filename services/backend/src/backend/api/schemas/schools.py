"""Schemas for the onboarding routes (decisions/0025)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.domain.models import School, SchoolStatus


class CreateSchoolRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    max_teachers: int = Field(ge=1, le=100_000)


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
