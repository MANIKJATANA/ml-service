"""student_groups

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-26

BP11a (decisions/0058): the class/section organizing structure. Adds a tenant-owned
``student_groups`` table (a class — name + optional grade/section, mirrors
``backend.db.models.StudentGroup``) and a nullable ``students.student_group_id`` FK
(ON DELETE SET NULL — deleting a class un-assigns its students, never deletes them).

Backend chain (alembic_version_backend). Additive — one new backend-owned table + one
nullable column + two indexes; no existing column changed, no ML chain. Fully reversible
(the down drops the column + its FK/index, then the table). Verified up→down→up on a
throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_groups",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("grade", sa.String(), nullable=True),
        sa.Column("section", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_student_groups_school", "student_groups", ["school_id", "name", "id"]
    )
    op.add_column(
        "students",
        sa.Column("student_group_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_students_student_group",
        "students",
        "student_groups",
        ["student_group_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_students_school_group",
        "students",
        ["school_id", "student_group_id", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_students_school_group", table_name="students")
    op.drop_constraint("fk_students_student_group", "students", type_="foreignkey")
    op.drop_column("students", "student_group_id")
    op.drop_index("ix_student_groups_school", table_name="student_groups")
    op.drop_table("student_groups")
