"""ORM models for the backend DB (decisions/0023).

These mirror the Alembic migrations exactly; application code never issues DDL — it
assumes the schema a migration already established (working rule; decisions/0007).
Backend table names never collide with the ML-owned tables in the same database
(decisions/0022). Phase 1 defined the two identity tables; Phase 4 adds ``students``
(decisions/0026); events/media land with their phases.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


class School(Base):
    """A tenant. ``id`` (as a string) is the opaque ``school_id`` sent to ML."""

    __tablename__ = "schools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    max_teachers: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'active'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("status IN ('active', 'suspended')", name="ck_schools_status"),
    )


class User(Base):
    """An account. ``school_id`` is null for a platform admin (global, no tenant)."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'active'")
    )
    # True until a staff-provisioned / temp-password account sets its own password
    # (migration 0002, decisions/0024).
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("email", name="uq_users_email"),
        Index("ix_users_school_role", "school_id", "role"),
        # These value lists MUST stay in lockstep with the domain enums (Role,
        # UserStatus): repos do Role(row.role), which raises on an unknown value.
        # Widen the enum and its CHECK together.
        CheckConstraint(
            "role IN ('platform_admin', 'school_admin', 'teacher', 'student')",
            name="ck_users_role",
        ),
        CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        # Tenant rule at the DB: platform admins are global (null school), everyone
        # else belongs to exactly one school (decisions/0023).
        CheckConstraint(
            "(role = 'platform_admin' AND school_id IS NULL) "
            "OR (role <> 'platform_admin' AND school_id IS NOT NULL)",
            name="ck_users_school_role",
        ),
    )


class Student(Base):
    """A student profile (decisions/0026). ``id`` (as a string) is the ML
    ``student_id``. Deleting the linked ``users`` row cascades this row away —
    the delete-student mechanism."""

    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    reference_photo_path: Mapped[str] = mapped_column(String, nullable=False)
    enrollment_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("user_id", name="uq_students_user"),
        Index("ix_students_school", "school_id"),
        # Lockstep with the EnrollmentStatus domain enum (repos do
        # EnrollmentStatus(row.enrollment_status)); widen enum + CHECK together.
        CheckConstraint(
            "enrollment_status IN ('pending', 'enrolled', 'failed')",
            name="ck_students_enrollment_status",
        ),
    )
