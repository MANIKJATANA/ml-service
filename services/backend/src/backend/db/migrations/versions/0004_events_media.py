"""events + media

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-10

Adds the ``events`` and ``media`` tables (decisions/0027). Mirrors
backend.db.models.Event / Media. ``events`` is created before ``media`` (FK order).
Both cascade from ``schools``; ``media`` cascades from ``events``; ``events.created_by``
uses ON DELETE SET NULL so an event outlives its creator's account.

Processing is **event-level**: ``events.processing_status`` is the status the FE reads;
``media.processing_status`` is per-photo. Both are written directly by the ML worker
(event ``processing``/``completed``; each photo ``completed``) over the shared DB — the
backend just reads them, no poller (decisions/0027). This chain's bookkeeping lives in
alembic_version_backend (env.py), separate from the ML chain in the same database.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "status", sa.String(), server_default=sa.text("'active'"), nullable=False
        ),
        sa.Column(
            "processing_status",
            sa.String(),
            server_default=sa.text("'not_started'"),
            nullable=False,
        ),
        sa.Column("enqueued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('active', 'archived')", name="ck_events_status"
        ),
        sa.CheckConstraint(
            "processing_status IN "
            "('not_started', 'queued', 'processing', 'completed')",
            name="ck_events_processing_status",
        ),
    )
    op.create_index("ix_events_school", "events", ["school_id"])
    op.create_index("ix_events_processing", "events", ["processing_status"])

    op.create_table(
        "media",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("storage_path", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column(
            "processing_status",
            sa.String(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "media_type IN ('image', 'video')", name="ck_media_type"
        ),
        sa.CheckConstraint(
            "processing_status IN ('pending', 'completed')",
            name="ck_media_processing_status",
        ),
    )
    op.create_index("ix_media_event", "media", ["school_id", "event_id"])
    op.create_index("ix_media_status", "media", ["processing_status"])


def downgrade() -> None:
    op.drop_index("ix_media_status", table_name="media")
    op.drop_index("ix_media_event", table_name="media")
    op.drop_table("media")
    op.drop_index("ix_events_processing", table_name="events")
    op.drop_index("ix_events_school", table_name="events")
    op.drop_table("events")
