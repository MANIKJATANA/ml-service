"""Class (student-group) use-cases (BP11a, decisions/0058).

Pure orchestration over the group + student repos — no HTTP, no RBAC (authorization is at
the route). The tenant (``school_id``) is the caller's token, passed in by the route, never
the URL. Owns the two "student ↔ class" relationships: single assignment (``PATCH
/v1/students/{id}``) and bulk assignment (``POST /v1/classes/{id}/members``). A student
belongs to at most one class (a nullable pointer); deleting a class un-assigns its students
(``ON DELETE SET NULL``), never deletes them.
"""

from __future__ import annotations

from backend.domain.errors import NotFoundError, ValidationError
from backend.domain.models import Student, StudentGroup, StudentGroupListing
from backend.domain.ports import StudentGroupRepository, StudentRepository


def _clean_name(name: str) -> str:
    # The schema owns the length bound (Field max_length); the strip + non-empty guard is the
    # one thing it can't express — ``min_length=1`` still admits an all-whitespace name.
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("class name is required")
    return cleaned


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class ClassService:
    def __init__(
        self, groups: StudentGroupRepository, students: StudentRepository
    ) -> None:
        self._groups = groups
        self._students = students

    async def list_classes(self, *, school_id: str) -> list[StudentGroupListing]:
        """The classes list: every class + its member count (bounded per school)."""
        groups = await self._groups.list_by_school(school_id)
        counts = await self._groups.student_counts(school_id)
        return [
            StudentGroupListing(group=g, student_count=counts.get(g.id, 0))
            for g in groups
        ]

    async def get_class(self, *, school_id: str, group_id: str) -> StudentGroup:
        group = await self._groups.get(school_id, group_id)
        if group is None:
            raise NotFoundError(f"class not found: {group_id}")
        return group

    async def create_class(
        self,
        *,
        school_id: str,
        name: str,
        grade: str | None,
        section: str | None,
    ) -> StudentGroup:
        return await self._groups.create(
            school_id=school_id,
            name=_clean_name(name),
            grade=_clean_optional(grade),
            section=_clean_optional(section),
        )

    async def update_class(
        self,
        *,
        school_id: str,
        group_id: str,
        name: str,
        grade: str | None,
        section: str | None,
    ) -> StudentGroup:
        group = await self._groups.update(
            school_id,
            group_id,
            name=_clean_name(name),
            grade=_clean_optional(grade),
            section=_clean_optional(section),
        )
        if group is None:
            raise NotFoundError(f"class not found: {group_id}")
        return group

    async def delete_class(self, *, school_id: str, group_id: str) -> None:
        if not await self._groups.delete(school_id, group_id):
            raise NotFoundError(f"class not found: {group_id}")

    async def assign_students(
        self, *, school_id: str, group_id: str, student_ids: list[str]
    ) -> int:
        """Bulk-add students to a class; returns the count assigned. Validates the class
        exists in this school first (foreign/unknown → 404) — never a cross-tenant write —
        then updates only in-school rows (a foreign student id is silently skipped)."""
        await self.get_class(school_id=school_id, group_id=group_id)
        return await self._students.set_group_bulk(
            school_id, student_group_id=group_id, student_ids=student_ids
        )

    async def set_student_group(
        self, *, school_id: str, student_id: str, group_id: str | None
    ) -> Student:
        """Assign one student to a class, or clear it with ``group_id=None`` (BP11a). Both
        the student and (when set) the target class must belong to the caller's school —
        else 404, never a cross-tenant move."""
        student = await self._students.get(school_id, student_id)
        if student is None:
            raise NotFoundError(f"student not found: {student_id}")
        if group_id is not None:
            await self.get_class(school_id=school_id, group_id=group_id)  # 404 if foreign
        await self._students.set_group(student_id, student_group_id=group_id)
        updated = await self._students.get(school_id, student_id)
        # Just fetched; a race that deletes it mid-call is vanishingly unlikely — fall back
        # to the pre-update read so the return type stays honest.
        return updated if updated is not None else student
