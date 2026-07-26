"""Teacher-delegation use-cases (BP11c, decisions/0060).

Pure orchestration over the teacher-class link + the group + user repos — no HTTP, no RBAC
(authorization is at the route: assignment is ``class:manage``, admin-only). The tenant
(``school_id``) is the caller's token, passed in by the route, never the URL.

Owns the teacher ↔ class relationship (many-to-many) from both surfaces — class-detail
("assign teachers to a class") and staff-row ("set a teacher's classes") — plus the teacher's
own "focus" scope (``my_group_ids``): the class ids their students/events lists default to.
Every write validates the class and the teacher belong to the caller's school first (a foreign
class/teacher → 404, never a cross-tenant link); delegation is convenience-only (focus, not a
hard boundary), so it never widens what a teacher can already reach — only the default view.
"""

from __future__ import annotations

from backend.domain.errors import NotFoundError
from backend.domain.models import Role, StudentGroup, User
from backend.domain.ports import (
    StudentGroupRepository,
    TeacherClassRepository,
    UserRepository,
)


class DelegationService:
    def __init__(
        self,
        links: TeacherClassRepository,
        groups: StudentGroupRepository,
        users: UserRepository,
    ) -> None:
        self._links = links
        self._groups = groups
        self._users = users

    # ---- class-detail surface: a class's teachers ----------------------

    async def list_class_teachers(
        self, *, school_id: str, group_id: str
    ) -> list[User]:
        """The teachers linked to one class (the class-detail roster). Validates the class is
        in-school first (foreign/unknown → 404)."""
        await self._require_class(school_id, group_id)
        ids = set(await self._links.list_teacher_ids_for_group(school_id, group_id))
        teachers = await self._users.list_by_school_and_role(school_id, Role.TEACHER)
        return [t for t in teachers if t.id in ids]

    async def assign_teachers(
        self, *, school_id: str, group_id: str, teacher_ids: list[str]
    ) -> int:
        """Bulk-link teachers to a class (class-detail "Assign teachers"). Validates the class
        is in-school (foreign → 404); each teacher id is validated in-school + role=teacher and
        a foreign/non-teacher id is silently skipped (never a cross-tenant link). Returns the
        count of valid teachers linked (idempotent — re-assigning an existing link is a no-op)."""
        await self._require_class(school_id, group_id)
        linked = 0
        for teacher_id in teacher_ids:
            if await self._is_school_teacher(school_id, teacher_id):
                await self._links.add(
                    school_id=school_id,
                    teacher_user_id=teacher_id,
                    student_group_id=group_id,
                )
                linked += 1
        return linked

    async def remove_class_teacher(
        self, *, school_id: str, group_id: str, teacher_id: str
    ) -> None:
        """Unlink one teacher from one class. Validates the class is in-school (foreign → 404);
        a non-existent link → 404 (never leaks another school's link)."""
        await self._require_class(school_id, group_id)
        removed = await self._links.remove(
            school_id=school_id,
            teacher_user_id=teacher_id,
            student_group_id=group_id,
        )
        if not removed:
            raise NotFoundError(f"teacher not assigned to class: {teacher_id}")

    # ---- staff surface: a teacher's classes ----------------------------

    async def list_teacher_classes(
        self, *, school_id: str, teacher_id: str
    ) -> list[StudentGroup]:
        """The classes one teacher is linked to (the staff-row chip). Validates the teacher is
        in-school + role=teacher first (foreign/non-teacher → 404)."""
        await self._require_teacher(school_id, teacher_id)
        return await self._classes_for(school_id, teacher_id)

    async def set_teacher_classes(
        self, *, school_id: str, teacher_id: str, group_ids: list[str]
    ) -> list[StudentGroup]:
        """Replace a teacher's whole class set (staff-row "Edit classes" PUT). Validates the
        teacher is in-school + role=teacher (foreign/non-teacher → 404); a foreign class id is
        silently skipped (tenant-safe). Returns the resulting classes."""
        await self._require_teacher(school_id, teacher_id)
        valid = [
            gid
            for gid in group_ids
            if await self._groups.get(school_id, gid) is not None
        ]
        await self._links.replace_for_teacher(
            school_id=school_id, teacher_user_id=teacher_id, student_group_ids=valid
        )
        return await self._classes_for(school_id, teacher_id)

    # ---- the caller's own scope (focus) --------------------------------

    async def my_classes(
        self, *, school_id: str, teacher_id: str
    ) -> list[StudentGroup]:
        """The caller-teacher's own classes (``GET /v1/classes/mine`` — labels the focus).
        No validation: the id is the authenticated actor's (an admin simply has none)."""
        return await self._classes_for(school_id, teacher_id)

    async def my_group_ids(
        self, *, school_id: str, teacher_id: str
    ) -> list[str]:
        """The caller-teacher's assigned class ids — their list "focus" scope. The route passes
        this as ``scope_group_ids`` to the students/events lists when ``mine=true``."""
        return await self._links.list_group_ids_for_teacher(school_id, teacher_id)

    # ---- helpers -------------------------------------------------------

    async def _classes_for(
        self, school_id: str, teacher_id: str
    ) -> list[StudentGroup]:
        ids = set(await self._links.list_group_ids_for_teacher(school_id, teacher_id))
        groups = await self._groups.list_by_school(school_id)
        return [g for g in groups if g.id in ids]

    async def _require_class(self, school_id: str, group_id: str) -> None:
        if await self._groups.get(school_id, group_id) is None:
            raise NotFoundError(f"class not found: {group_id}")

    async def _require_teacher(self, school_id: str, teacher_id: str) -> User:
        """Fetch a teacher the caller may manage: exists, in ``school_id``, role=teacher — else
        404 (never leak a user of another school/role), mirroring ``_require_managed_user``."""
        user = await self._users.get(teacher_id)
        if user is None or user.school_id != school_id or user.role is not Role.TEACHER:
            raise NotFoundError(f"teacher not found: {teacher_id}")
        return user

    async def _is_school_teacher(self, school_id: str, teacher_id: str) -> bool:
        user = await self._users.get(teacher_id)
        return (
            user is not None
            and user.school_id == school_id
            and user.role is Role.TEACHER
        )
