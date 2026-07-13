"""notifications: event announce fields + notification_reads

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-14

Adds the BP4 distribution surface (decisions/0041). Mirrors backend.db.models.

- ``events`` gains ``auto_notify`` (announce to students on completion — a live gate) and
  ``notified_at`` (last manual "Notify students" push). The student "new photos" signal is
  DERIVED (no per-student rows written at completion): announced = ``notified_at`` set OR
  (``auto_notify`` AND ``completed_at`` set).
- ``notification_reads`` records per-(student, event) "seen" state so the derived signal can
  compute unseen = no read OR ``seen_at`` < the effective announce time. Natural key
  ``(student_id, event_id)`` (the upsert key); ``school_id`` denormalized for tenant scans;
  an event-side index for the staff roster.

Backend chain (alembic_version_backend). Touches only backend-owned tables — no ML chain,
no ``matches``.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "events",
        sa.Column(
            "auto_notify",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.add_column(
        "events",
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "notification_reads",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
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
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "student_id", "event_id", name="uq_notification_reads_pair"
        ),
    )
    op.create_index(
        "ix_notification_reads_student", "notification_reads", ["school_id", "student_id"]
    )
    op.create_index(
        "ix_notification_reads_event", "notification_reads", ["school_id", "event_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_notification_reads_event", table_name="notification_reads")
    op.drop_index("ix_notification_reads_student", table_name="notification_reads")
    op.drop_table("notification_reads")
    op.drop_column("events", "notified_at")
    op.drop_column("events", "auto_notify")
