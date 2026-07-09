"""students

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

Adds the ``students`` table (decisions/0026). Mirrors backend.db.models.Student.
``user_id``'s ON DELETE CASCADE is the delete-student mechanism (deleting the login
row removes the profile). This chain's bookkeeping lives in alembic_version_backend
(env.py), separate from the ML chain in the same database.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "students",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("reference_photo_path", sa.String(), nullable=False),
        sa.Column(
            "enrollment_status",
            sa.String(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", name="uq_students_user"),
        sa.CheckConstraint(
            "enrollment_status IN ('pending', 'enrolled', 'failed')",
            name="ck_students_enrollment_status",
        ),
    )
    op.create_index("ix_students_school", "students", ["school_id"])


def downgrade() -> None:
    op.drop_index("ix_students_school", table_name="students")
    op.drop_table("students")
