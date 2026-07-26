"""teacher_classes + events.student_group_id

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-26

BP11c (decisions/0060): teacher delegation. Adds a tenant-owned ``teacher_classes`` join
table (a teacher ↔ class many-to-many, both FKs ``ON DELETE CASCADE`` so deleting a teacher
or a class just drops the link — never a student/teacher) and, on ``events``, a nullable
``student_group_id`` FK (**ON DELETE SET NULL** — deleting a class un-tags its events, never
deletes them), mirroring BP11b's ``events.category_id``.

Backend chain (alembic_version_backend). Additive — one new backend-owned table + one
nullable column + indexes; no existing column changed, no ML chain. Fully reversible (the
down drops the column/its FK/index, then the table). Verified up->down->up on a throwaway
Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teacher_classes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("teacher_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_group_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["teacher_user_id"], ["users.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["student_group_id"], ["student_groups.id"], ondelete="CASCADE"
        ),
        # A teacher is linked to a class at most once (the assignment upsert key).
        sa.UniqueConstraint(
            "teacher_user_id", "student_group_id", name="uq_teacher_classes_pair"
        ),
    )
    # Look up both directions: a teacher's classes (the focus scope) and a class's teachers.
    op.create_index(
        "ix_teacher_classes_teacher",
        "teacher_classes",
        ["school_id", "teacher_user_id"],
    )
    op.create_index(
        "ix_teacher_classes_group",
        "teacher_classes",
        ["school_id", "student_group_id"],
    )
    op.add_column(
        "events",
        sa.Column("student_group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_events_student_group",
        "events",
        "student_groups",
        ["student_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_events_school_group",
        "events",
        ["school_id", "student_group_id", "event_date", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_events_school_group", table_name="events")
    op.drop_constraint("fk_events_student_group", "events", type_="foreignkey")
    op.drop_column("events", "student_group_id")
    op.drop_index("ix_teacher_classes_group", table_name="teacher_classes")
    op.drop_index("ix_teacher_classes_teacher", table_name="teacher_classes")
    op.drop_table("teacher_classes")
