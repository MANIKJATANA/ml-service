"""download_audit

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-16

Adds the BP8b access/download audit (decisions/0050). Mirrors backend.db.models.DownloadAudit.

An append-only, backend-owned record of entitled media downloads: the backend writes a row
every time it mints a signed download URL for an entitled caller. ``actor_role`` is
denormalized so the log survives the account (``actor_user_id`` → SET NULL on delete);
``subject_student_id`` is set only for a student's own self-download. The composite indexes
serve the per-media history + the school-wide log (and its event/student filters).

Backend chain (alembic_version_backend). Touches only a new backend-owned table — no ML
chain, no change to existing tables. Fully reversible (the down drops the table).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "download_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("subject_student_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["subject_student_id"], ["students.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "actor_role IN ('platform_admin', 'school_admin', 'teacher', 'student')",
            name="ck_download_audit_actor_role",
        ),
    )
    op.create_index(
        "ix_download_audit_media",
        "download_audit",
        ["school_id", "media_id", "created_at"],
    )
    op.create_index(
        "ix_download_audit_school", "download_audit", ["school_id", "created_at"]
    )
    op.create_index(
        "ix_download_audit_event",
        "download_audit",
        ["school_id", "event_id", "created_at"],
    )
    op.create_index(
        "ix_download_audit_student",
        "download_audit",
        ["school_id", "subject_student_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_download_audit_student", table_name="download_audit")
    op.drop_index("ix_download_audit_event", table_name="download_audit")
    op.drop_index("ix_download_audit_school", table_name="download_audit")
    op.drop_index("ix_download_audit_media", table_name="download_audit")
    op.drop_table("download_audit")
