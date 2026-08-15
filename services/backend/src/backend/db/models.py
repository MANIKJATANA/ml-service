"""ORM models for the backend DB (decisions/0023).

These mirror the Alembic migrations exactly; application code never issues DDL — it
assumes the schema a migration already established (working rule; decisions/0007).
Backend table names never collide with the ML-owned tables in the same database
(decisions/0022). Phase 1 defined the two identity tables; Phase 4 adds ``students``
(decisions/0026); Phase 5 adds ``events`` + ``media`` (decisions/0027).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
    # Last successful login (migration 0016, BP14). Null until the account first signs in;
    # never stamped on token refresh (not an interactive sign-in). Powers the sign-in rate.
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Bumped on every password change/reset (migration 0017, BP18d) to revoke a user's older
    # sessions: the `tv` claim in each JWT is compared to this on every request + refresh, so a
    # changed/reset password invalidates all previously-issued tokens.
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
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
    # Nullable (BP7d): a bulk-imported student starts photoless (pending) until one is set.
    reference_photo_path: Mapped[str | None] = mapped_column(String, nullable=True)
    # BP17: a stored downscaled sibling of the reference photo (display-only avatar). Null
    # for a photoless student + pre-BP17 rows; ML enrollment reads reference_photo_path.
    reference_photo_thumbnail_path: Mapped[str | None] = mapped_column(
        String, nullable=True
    )
    enrollment_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'")
    )
    # Why enrollment failed (BP7b) — null unless enrollment_status='failed'. Lockstep
    # with the EnrollmentFailureReason domain enum (widen enum + CHECK together).
    enrollment_failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    # BP11a (migration 0013): the class/section this student belongs to, or NULL (un-classed).
    # ON DELETE SET NULL — deleting a class un-assigns its students, never deletes them.
    student_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_groups.id", ondelete="SET NULL"),
        nullable=True,
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
        # BP11a: filter/group the students list by class within a school.
        Index("ix_students_school_group", "school_id", "student_group_id", "id"),
        # Lockstep with the EnrollmentStatus domain enum (repos do
        # EnrollmentStatus(row.enrollment_status)); widen enum + CHECK together.
        CheckConstraint(
            "enrollment_status IN ('pending', 'enrolled', 'failed')",
            name="ck_students_enrollment_status",
        ),
        CheckConstraint(
            "enrollment_failure_reason IS NULL OR enrollment_failure_reason IN "
            "('no_face', 'ml_unavailable', 'error')",
            name="ck_students_enrollment_failure_reason",
        ),
    )


class StudentGroup(Base):
    """A class / section (BP11a, migration 0013, decisions/0058). Tenant-owned; a student
    points at one via ``students.student_group_id`` (SET NULL on delete). Bounded per school
    (a few dozen), so its list read is unpaginated."""

    __tablename__ = "student_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    grade: Mapped[str | None] = mapped_column(String, nullable=True)
    section: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (Index("ix_student_groups_school", "school_id", "name", "id"),)


class TeacherClass(Base):
    """A teacher ↔ class delegation link (BP11c, migration 0015, decisions/0060).

    Many-to-many: a teacher can own several classes; a class can have several teachers.
    Both FKs ``ON DELETE CASCADE`` — deleting a teacher (a ``users`` row) or a class drops
    the link, never the other side. Tenant-owned (``school_id`` denormalized for scoped
    scans). A teacher's assigned classes drive their list "focus" scope."""

    __tablename__ = "teacher_classes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    teacher_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_group_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "teacher_user_id", "student_group_id", name="uq_teacher_classes_pair"
        ),
        Index("ix_teacher_classes_teacher", "school_id", "teacher_user_id"),
        Index("ix_teacher_classes_group", "school_id", "student_group_id"),
    )


class Event(Base):
    """An event (decisions/0027). ``id`` (as a string) is the ML ``event_id``.
    ``created_by`` uses ON DELETE SET NULL so an event outlives its creator's account.
    ``status`` is the lifecycle; ``processing_status`` is the event-level inference state
    the FE reads (the backend sets ``queued`` on Process; the ML worker writes
    ``processing``/``completed`` directly — decisions/0027)."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'active'")
    )
    processing_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'not_started'")
    )
    enqueued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # BP4 distribution (migration 0005, decisions/0041): auto-announce on completion +
    # the last manual "Notify students" timestamp.
    auto_notify: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # BP11b (migration 0014): a free-text term + the event's category (a tenant-owned
    # event_categories row). category_id SET NULL on category delete — un-tags, never deletes.
    term: Mapped[str | None] = mapped_column(String, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("event_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    # BP11c (migration 0015): the class this event belongs to, or NULL (school-wide). SET NULL
    # on class delete — un-tags its events, never deletes them. A teacher's "focus" scope reads it.
    student_group_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("student_groups.id", ondelete="SET NULL"),
        nullable=True,
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
        Index("ix_events_school", "school_id"),
        Index("ix_events_processing", "processing_status"),
        # BP11b: filter/calendar the events list by category within a school.
        Index(
            "ix_events_school_category",
            "school_id",
            "category_id",
            "event_date",
            "id",
        ),
        # BP11c: filter events by class + a teacher's focus scope within a school.
        Index(
            "ix_events_school_group",
            "school_id",
            "student_group_id",
            "event_date",
            "id",
        ),
        # Lockstep with the EventStatus / EventProcessingStatus domain enums; widen
        # each enum and its CHECK together.
        CheckConstraint(
            "status IN ('active', 'archived')", name="ck_events_status"
        ),
        CheckConstraint(
            "processing_status IN "
            "('not_started', 'queued', 'processing', 'completed')",
            name="ck_events_processing_status",
        ),
    )


class EventCategory(Base):
    """A tenant-owned event category (BP11b, migration 0014, decisions/0059). Seeded with the 6
    defaults on school-create; admins/staff add more. An event points at one via
    ``events.category_id`` (SET NULL on delete). Bounded per school."""

    __tablename__ = "event_categories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
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
        UniqueConstraint("school_id", "name", name="uq_event_categories_school_name"),
        Index("ix_event_categories_school", "school_id", "name", "id"),
    )


class Media(Base):
    """One uploaded event photo + its per-photo processing state (decisions/0027).
    ``id`` (as a string) is the ML ``media_id``; ``storage_path`` is the ML ``media_uri``.
    Recording a photo enqueues nothing — processing is event-level."""

    __tablename__ = "media"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_path: Mapped[str] = mapped_column(String, nullable=False)
    # BP17: a stored downscaled sibling of storage_path (display-only tile preview). Null for
    # pre-BP17 media + all video; the ML worker reads storage_path (the full-res).
    thumbnail_path: Mapped[str | None] = mapped_column(String, nullable=True)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'pending'")
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
        Index("ix_media_event", "school_id", "event_id"),
        Index("ix_media_status", "processing_status"),
        # Lockstep with the MediaType / MediaProcessingStatus domain enums.
        CheckConstraint(
            "media_type IN ('image', 'video')", name="ck_media_type"
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'completed', 'failed')",
            name="ck_media_processing_status",
        ),
    )


class NotificationRead(Base):
    """Per-(student, event) 'seen' state for the in-app new-photos signal (migration 0005,
    decisions/0041). One row per student×event; ``seen_at`` moves forward when the student
    opens that event's photos. The natural key is ``(student_id, event_id)`` (the upsert
    key); ``school_id`` is denormalized for tenant-scoped scans (like ``media``/``matches``)."""

    __tablename__ = "notification_reads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
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
        UniqueConstraint("student_id", "event_id", name="uq_notification_reads_pair"),
        Index("ix_notification_reads_student", "school_id", "student_id"),
        Index("ix_notification_reads_event", "school_id", "event_id"),
    )


class MatchCorrection(Base):
    """A staff/student correction over the ML ``matches`` (migration 0006, decisions/0042).

    Backend-owned; keyed on the stable ``(media_id, student_id)`` pair (the ML match's
    natural key) so it survives higher-confidence re-inference — no FK to the ML-owned
    ``matches`` table. The gallery reads overlay these: ``rejected`` hides a match (+ blocks
    the student's download); ``added`` unions a missed student in; ``confirmed`` stands.
    ``resolves_review`` is set when the corrected match was ``needs_review`` at the time."""

    __tablename__ = "match_corrections"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media.id", ondelete="CASCADE"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    verdict: Mapped[str] = mapped_column(String, nullable=False)
    resolves_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    # The corrector (staff user, or the student themselves for a self "not me"). SET NULL so
    # a correction outlives the account that made it.
    corrected_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reason: Mapped[str | None] = mapped_column(String, nullable=True)
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
        UniqueConstraint("media_id", "student_id", name="uq_match_corrections_pair"),
        Index("ix_match_corrections_media", "school_id", "media_id"),
        Index("ix_match_corrections_event", "school_id", "event_id"),
        Index("ix_match_corrections_student", "school_id", "student_id"),
        # Lockstep with the MatchVerdict domain enum.
        CheckConstraint(
            "verdict IN ('confirmed', 'rejected', 'added')",
            name="ck_match_corrections_verdict",
        ),
    )


class DownloadAudit(Base):
    """An append-only record of one entitled media download (migration 0010, decisions/0050).

    Backend-owned trust audit (BP8b): the backend writes a row every time it mints a signed
    download URL for an entitled caller. ``actor_role`` is denormalized at write time so the
    log still shows who + in what capacity after the account is deleted (``actor_user_id`` →
    NULL). ``subject_student_id`` is the student on a *student self-download* (else NULL for
    staff). Rows are immutable — no ``updated_at``, no update/delete path. The composite
    indexes serve the per-media history and the school-wide log (+ its event/student
    filters); ``created_at`` trails each so a backward scan orders newest-first."""

    __tablename__ = "download_audit"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    school_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=False,
    )
    media_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("media.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    # SET NULL so the audit row outlives the account that made the download.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_role: Mapped[str] = mapped_column(String, nullable=False)
    # The downloading student, on a student self-download (else NULL for staff).
    subject_student_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("students.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_download_audit_media", "school_id", "media_id", "created_at"),
        Index("ix_download_audit_school", "school_id", "created_at"),
        Index("ix_download_audit_event", "school_id", "event_id", "created_at"),
        Index(
            "ix_download_audit_student", "school_id", "subject_student_id", "created_at"
        ),
        # Lockstep with the Role domain enum.
        CheckConstraint(
            "actor_role IN ('platform_admin', 'school_admin', 'teacher', 'student')",
            name="ck_download_audit_actor_role",
        ),
    )
