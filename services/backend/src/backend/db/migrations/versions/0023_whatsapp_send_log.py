"""whatsapp_send_log

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-30

Adds the W2 WhatsApp send audit. Mirrors backend.db.models.WhatsAppSendLog.

An append-only, backend-owned record of every WhatsApp send attempt: the
``WhatsAppShareService`` writes one row per media it attempts (``sent``/``failed``/
``skipped``). ``actor_role`` is denormalized so the trail survives the account
(``actor_user_id`` → SET NULL on delete). ``student_id`` and ``media_id`` are SET NULL
too — the spend/audit FACT outlives an erased student (BP8e) / deleted media (the audit
outlives its subject), so those columns are nullable, un-CASCADEd. The recipient phone
number is DELIBERATELY NOT a column (PII-free; the row is identified by ``student_id``/
``media_id``, never the number). The ``ix_whatsapp_send_log_school`` composite serves the
monthly budget count (``sent`` rows since the UTC month start); ``ix_whatsapp_send_log_student``
serves a per-student send history.

Backend chain (alembic_version_backend). Touches only a new backend-owned table — no ML
chain, no change to existing tables. Fully reversible (the down drops the indexes then the
table). Verified up→down→up on a throwaway Postgres (wa_w2_migtest).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "whatsapp_send_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("media_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(), nullable=False),
        sa.Column("sender_number", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("provider_message_id", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["school_id"], ["schools.id"], ondelete="CASCADE"),
        # SET NULL so the spend/audit fact outlives an erased student / deleted media.
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "status IN ('sent', 'failed', 'skipped')",
            name="ck_whatsapp_send_log_status",
        ),
        sa.CheckConstraint(
            "actor_role IN ('platform_admin', 'school_admin', 'teacher', 'student')",
            name="ck_whatsapp_send_log_actor_role",
        ),
    )
    op.create_index(
        "ix_whatsapp_send_log_school",
        "whatsapp_send_log",
        ["school_id", "created_at"],
    )
    op.create_index(
        "ix_whatsapp_send_log_student",
        "whatsapp_send_log",
        ["school_id", "student_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_whatsapp_send_log_student", table_name="whatsapp_send_log")
    op.drop_index("ix_whatsapp_send_log_school", table_name="whatsapp_send_log")
    op.drop_table("whatsapp_send_log")
