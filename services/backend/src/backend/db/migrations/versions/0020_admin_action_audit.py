"""admin_action_audit

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-30

Adds the BP28b admin-action audit (R4-A25). Mirrors backend.db.models.AdminActionAudit.

An append-only, backend-owned record of governance-lifecycle actions: the single-writer
services (student/onboarding) write a row after each create/disable/enable/delete of a
student, staff invite/lifecycle, or school edit. ``actor_role`` is denormalized so the trail
survives the account (``actor_user_id`` → SET NULL on delete); ``target_id`` is a
heterogeneous student/staff/school id (NO FK — like ``match_corrections`` has no FK to the
ML-owned ``matches``); ``target_label`` is a human label captured at write time. The composite
indexes serve the school-wide log (newest-first) + its target/actor/action drill-downs.

Backend chain (alembic_version_backend). Touches only a new backend-owned table — no ML
chain, no change to existing tables. Fully reversible (the down drops the indexes then the
table). Verified up→down→up on a throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_action_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_label", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        # NB: target_id has NO foreign key — it's a heterogeneous student/staff/school id.
        sa.CheckConstraint(
            "actor_role IN ('platform_admin', 'school_admin', 'teacher', 'student')",
            name="ck_admin_action_audit_actor_role",
        ),
        sa.CheckConstraint(
            "action IN ('student_created', 'student_disabled', 'student_enabled', "
            "'student_deleted', 'student_reenrolled', 'student_invite_resent', "
            "'staff_created', 'staff_disabled', 'staff_enabled', 'staff_invite_resent', "
            "'school_updated')",
            name="ck_admin_action_audit_action",
        ),
        sa.CheckConstraint(
            "target_type IN ('student', 'staff', 'school')",
            name="ck_admin_action_audit_target_type",
        ),
    )
    op.create_index(
        "ix_admin_action_audit_school",
        "admin_action_audit",
        ["school_id", "created_at"],
    )
    op.create_index(
        "ix_admin_action_audit_target",
        "admin_action_audit",
        ["school_id", "target_type", "target_id", "created_at"],
    )
    op.create_index(
        "ix_admin_action_audit_actor",
        "admin_action_audit",
        ["school_id", "actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_admin_action_audit_action",
        "admin_action_audit",
        ["school_id", "action", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_admin_action_audit_action", table_name="admin_action_audit")
    op.drop_index("ix_admin_action_audit_actor", table_name="admin_action_audit")
    op.drop_index("ix_admin_action_audit_target", table_name="admin_action_audit")
    op.drop_index("ix_admin_action_audit_school", table_name="admin_action_audit")
    op.drop_table("admin_action_audit")
