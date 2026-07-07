"""initial backend schema: schools, users

Revision ID: 0001
Revises:
Create Date: 2026-07-08

Mirrors backend.db.models (decisions/0023). This chain's bookkeeping lives in
alembic_version_backend (env.py), separate from the ML chain in the same database.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schools",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("max_teachers", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(), server_default=sa.text("'active'"), nullable=False
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
        sa.CheckConstraint("status IN ('active', 'suspended')", name="ck_schools_status"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column(
            "status", sa.String(), server_default=sa.text("'active'"), nullable=False
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
        sa.UniqueConstraint("email", name="uq_users_email"),
        sa.CheckConstraint(
            "role IN ('platform_admin', 'school_admin', 'teacher', 'student')",
            name="ck_users_role",
        ),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="ck_users_status"),
        sa.CheckConstraint(
            "(role = 'platform_admin' AND school_id IS NULL) "
            "OR (role <> 'platform_admin' AND school_id IS NOT NULL)",
            name="ck_users_school_role",
        ),
    )
    op.create_index("ix_users_school_role", "users", ["school_id", "role"])


def downgrade() -> None:
    op.drop_index("ix_users_school_role", table_name="users")
    op.drop_table("users")
    op.drop_table("schools")
