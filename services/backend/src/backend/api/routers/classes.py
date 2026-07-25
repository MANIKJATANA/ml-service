"""Class (student-group) routes (BP11a, decisions/0058).

The organizing structure for students. Tenant isolation: the school is taken from the
authenticated user's token (``tenant_of``), never the URL or body — a ``group_id`` from
another school resolves to 404. Split by capability: lifecycle (create/edit/delete) needs
``class:manage`` (school_admin only); reads + bulk student assignment ride on
``student:manage`` (admin + teacher), the day-to-day roster action.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.classes import (
    AssignStudentsRequest,
    AssignStudentsResponse,
    ClassListResponse,
    ClassResponse,
    CreateClassRequest,
    UpdateClassRequest,
)
from backend.domain.models import User
from backend.domain.permissions import Permission

router = APIRouter(prefix="/v1/classes", tags=["classes"])

# Lifecycle is admin-only (class:manage); reads + assignment are both roles (student:manage).
ClassManager = Annotated[User, Depends(require_permissions(Permission.CLASS_MANAGE))]
StudentManager = Annotated[User, Depends(require_permissions(Permission.STUDENT_MANAGE))]


@router.get("", response_model=ClassListResponse)
async def list_classes(
    container: ContainerDep, actor: StudentManager
) -> ClassListResponse:
    """Every class in the school + its student count (bounded — unpaginated). Also feeds the
    students-list class filter."""
    listings = await container.class_service().list_classes(school_id=tenant_of(actor))
    return ClassListResponse.from_listings(listings)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ClassResponse)
async def create_class(
    body: CreateClassRequest, container: ContainerDep, actor: ClassManager
) -> ClassResponse:
    group = await container.class_service().create_class(
        school_id=tenant_of(actor),
        name=body.name,
        grade=body.grade,
        section=body.section,
    )
    return ClassResponse.from_group(group)


@router.get("/{group_id}", response_model=ClassResponse)
async def get_class(
    group_id: str, container: ContainerDep, actor: StudentManager
) -> ClassResponse:
    group = await container.class_service().get_class(
        school_id=tenant_of(actor), group_id=group_id
    )
    return ClassResponse.from_group(group)


@router.patch("/{group_id}", response_model=ClassResponse)
async def update_class(
    group_id: str,
    body: UpdateClassRequest,
    container: ContainerDep,
    actor: ClassManager,
) -> ClassResponse:
    group = await container.class_service().update_class(
        school_id=tenant_of(actor),
        group_id=group_id,
        name=body.name,
        grade=body.grade,
        section=body.section,
    )
    return ClassResponse.from_group(group)


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(
    group_id: str, container: ContainerDep, actor: ClassManager
) -> None:
    """Delete a class. Its students are un-assigned (SET NULL), never deleted."""
    await container.class_service().delete_class(
        school_id=tenant_of(actor), group_id=group_id
    )


@router.post("/{group_id}/members", response_model=AssignStudentsResponse)
async def assign_students(
    group_id: str,
    body: AssignStudentsRequest,
    container: ContainerDep,
    actor: StudentManager,
) -> AssignStudentsResponse:
    """Bulk-add students to a class (BP11a). Tenant from the token; a foreign class → 404, a
    foreign student id is silently skipped. Returns the count assigned."""
    assigned = await container.class_service().assign_students(
        school_id=tenant_of(actor), group_id=group_id, student_ids=body.student_ids
    )
    return AssignStudentsResponse(assigned=assigned)
