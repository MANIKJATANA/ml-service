"""Backend domain models — pure, frozen value types (no third-party imports).

Ids are ``str`` (canonical UUID strings); the DB stores them as ``uuid`` and the
repositories convert on read (decisions/0023). The string form is exactly what the
ML service receives, so no conversion happens at the ML boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class Role(StrEnum):
    PLATFORM_ADMIN = "platform_admin"
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"
    STUDENT = "student"


class SchoolStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class School:
    id: str
    name: str
    max_teachers: int
    status: SchoolStatus
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class User:
    id: str
    school_id: str | None  # None -> platform_admin (global, no tenant)
    email: str
    password_hash: str
    role: Role
    status: UserStatus
    created_at: datetime
    updated_at: datetime
