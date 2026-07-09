"""Student routes — create + ML enrollment (decisions/0026).

Requires the `student:manage` permission (school_admin or teacher). Tenant isolation:
the school is taken from the authenticated user's token (`tenant_of`), never from the
URL or body — a `student_id` from another school resolves to 404. The reference photo
never passes through the backend: the frontend uploads it directly to Supabase via the
signed URL from `POST /v1/students/upload-url`, then submits the object path here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from backend.api.deps import ContainerDep, require_permissions, tenant_of
from backend.api.schemas.students import (
    CreateStudentRequest,
    StudentResponse,
    UploadUrlResponse,
)
from backend.domain.models import User
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


@router.post("", status_code=status.HTTP_201_CREATED, response_model=StudentResponse)
async def create_student(
    body: CreateStudentRequest, container: ContainerDep, actor: StudentManager
) -> StudentResponse:
    student = await container.student_service().create_student(
        school_id=tenant_of(actor),
        name=body.name,
        email=body.email,
        password=body.password,
        reference_photo_path=body.reference_photo_path,
    )
    return StudentResponse.from_student(student)


@router.get("", response_model=list[StudentResponse])
async def list_students(
    container: ContainerDep, actor: StudentManager
) -> list[StudentResponse]:
    students = await container.student_service().list_students(
        school_id=tenant_of(actor)
    )
    return [StudentResponse.from_student(s) for s in students]


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


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str, container: ContainerDep, actor: StudentManager
) -> None:
    await container.student_service().delete_student(
        school_id=tenant_of(actor), student_id=student_id
    )
