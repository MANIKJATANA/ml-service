"""Class (student-group) API schemas (BP11a, decisions/0058).

Request/response shapes for the class routes. A class is a tenant-owned label (name +
optional grade/section) a school organizes students by. Lifecycle (create/edit/delete)
requires ``class:manage`` (school_admin); reads + student assignment ride on
``student:manage`` (admin + teacher).
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from backend.domain.models import StudentGroup, StudentGroupListing

# The largest number of students one bulk-assign call can move into a class — over it is a 422.
# Higher than the CSV-import cap (500, ``schemas/students.py``) on purpose: assigning can span a
# whole school (~800) and is a cheap id-only UPDATE (no per-row provisioning like import). The FE
# can't assemble this many anyway (it picks from the searched list) — this is just an abuse ceiling.
_MAX_ASSIGN = 1000


class CreateClassRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=50)
    section: str | None = Field(default=None, max_length=50)


class UpdateClassRequest(BaseModel):
    """Full replace of the editable fields (the edit form always sends all three)."""

    name: str = Field(min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=50)
    section: str | None = Field(default=None, max_length=50)


class AssignStudentsRequest(BaseModel):
    """Bulk-add students to a class (BP11a). Ids are validated + tenant-scoped in the repo
    (a foreign/unknown id is silently skipped, never a cross-tenant write)."""

    student_ids: list[str] = Field(min_length=1, max_length=_MAX_ASSIGN)


class ClassResponse(BaseModel):
    id: str
    school_id: str
    name: str
    grade: str | None
    section: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_group(cls, g: StudentGroup) -> ClassResponse:
        return cls(
            id=g.id,
            school_id=g.school_id,
            name=g.name,
            grade=g.grade,
            section=g.section,
            created_at=g.created_at,
            updated_at=g.updated_at,
        )


class ClassListItem(ClassResponse):
    """A classes-list row: the class + how many students are in it."""

    student_count: int

    @classmethod
    def from_listing(cls, listing: StudentGroupListing) -> ClassListItem:
        return cls(
            **ClassResponse.from_group(listing.group).model_dump(),
            student_count=listing.student_count,
        )


class AssignStudentsResponse(BaseModel):
    assigned: int


# One pasted email (BP24). Length-capped (abuse guard); the batch count reuses the id cap.
_Email = Annotated[str, StringConstraints(min_length=1, max_length=320)]


class AssignStudentsByEmailRequest(BaseModel):
    """Bulk-assign students to a class by pasted email (BP24). Emails are resolved to in-school
    students in the service (case-insensitive; an unknown email → unmatched, never a
    cross-tenant enumerate)."""

    emails: list[_Email] = Field(min_length=1, max_length=_MAX_ASSIGN)


class AssignStudentsByEmailResponse(BaseModel):
    """The by-email assign result: how many were assigned + the emails that matched no student
    in this school (so the admin can fix typos)."""

    assigned: int
    unmatched: list[str]


# ---- BP11c teacher delegation (decisions/0060) --------------------------

# The largest number of teachers one class-assign call, or classes one teacher-set call, can
# carry — well above any real school's staff/class count; over it is a 422 (an abuse ceiling).
_MAX_DELEGATION = 200


class AssignTeachersRequest(BaseModel):
    """Bulk-link teachers to a class (BP11c). Ids are validated + tenant-scoped in the service
    (a foreign/non-teacher id is silently skipped, never a cross-tenant link)."""

    teacher_ids: list[str] = Field(min_length=1, max_length=_MAX_DELEGATION)


class AssignTeachersResponse(BaseModel):
    assigned: int


class SetTeacherClassesRequest(BaseModel):
    """Replace a teacher's whole class set (the staff-row "Edit classes" PUT). An empty list
    clears the teacher's classes; a foreign class id is silently skipped in the service."""

    group_ids: list[str] = Field(default_factory=list, max_length=_MAX_DELEGATION)


class ClassRefListResponse(BaseModel):
    """A plain list of classes (no counts) — a teacher's assigned classes / "my classes"."""

    items: list[ClassResponse]

    @classmethod
    def from_groups(cls, groups: list[StudentGroup]) -> ClassRefListResponse:
        return cls(items=[ClassResponse.from_group(g) for g in groups])


class ClassListResponse(BaseModel):
    """The classes list. Unpaginated — classes are bounded per school (a few dozen); the FE
    also uses this list to populate the students-list class filter."""

    items: list[ClassListItem]

    @classmethod
    def from_listings(
        cls, listings: list[StudentGroupListing]
    ) -> ClassListResponse:
        return cls(items=[ClassListItem.from_listing(x) for x in listings])
