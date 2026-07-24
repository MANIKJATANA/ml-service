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

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.pagination import (
    DEFAULT_PAGE_SIZE,
    LimitQuery,
    OffsetQuery,
    SearchQuery,
    is_descending,
)
from backend.api.schemas.students import (
    BulkImportRequest,
    BulkImportResponse,
    CreateStudentRequest,
    ProvisionedStudentResponse,
    SetReferencePhotoRequest,
    StudentListPageResponse,
    StudentResponse,
    UploadUrlResponse,
)
from backend.domain.models import EnrollmentStatus, SortDir, StudentSort, User
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
    return UploadUrlResponse(
        upload_url=signed.upload_url,
        object_path=signed.object_path,
        max_upload_mb=container.settings.max_upload_mb,
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
        rows=[(r.name, r.email) for r in body.students],
    )
    return BulkImportResponse.from_results(results)


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
) -> StudentListPageResponse:
    """One page of the students list (BP9): server search (name/email), sort (incl. the
    whole-list appearance/event count columns), and enrollment-status filter."""
    page = await container.listing_service().list_students_page(
        school_id=tenant_of(actor),
        limit=limit,
        offset=offset,
        q=q,
        sort=sort,
        descending=is_descending(dir),
        status=status,
    )
    return StudentListPageResponse.from_page(page)


@router.get("/{student_id}", response_model=StudentResponse)
async def get_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> StudentResponse:
    student = await container.student_service().get_student(
        school_id=tenant_of(actor), student_id=student_id
    )
    return StudentResponse.from_student(student)


@router.post("/{student_id}/enroll", response_model=StudentResponse)
async def enroll_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> StudentResponse:
    student = await container.student_service().enroll_student(
        school_id=tenant_of(actor), student_id=student_id
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
    )
    return StudentResponse.from_student(student)


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> None:
    await container.student_service().delete_student(
        school_id=tenant_of(actor), student_id=student_id
    )
