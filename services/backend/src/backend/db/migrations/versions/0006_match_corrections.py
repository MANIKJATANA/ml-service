"""match_corrections

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-14

Adds the BP5 trust/accuracy overlay (decisions/0042). Mirrors backend.db.models.MatchCorrection.

A backend-owned correction over the ML ``matches``, keyed on the stable ``(media_id,
student_id)`` pair (no FK to the ML-owned ``matches`` — that table's ``match_id`` churns on
higher-confidence re-inference, but the pair is stable). The gallery reads overlay these:
``rejected`` hides a match (+ blocks the student's download), ``added`` unions a missed
student in, ``confirmed`` stands. ``resolves_review`` marks a correction made against a
``needs_review`` match (the dashboard's unresolved-review count subtracts these).

Backend chain (alembic_version_backend). Touches only backend-owned tables — no ML chain.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_corrections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("student_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column(
            "resolves_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("corrected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(), nullable=True),
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
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["students.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["corrected_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint(
            "media_id", "student_id", name="uq_match_corrections_pair"
        ),
        sa.CheckConstraint(
            "verdict IN ('confirmed', 'rejected', 'added')",
            name="ck_match_corrections_verdict",
        ),
    )
    op.create_index(
        "ix_match_corrections_media", "match_corrections", ["school_id", "media_id"]
    )
    op.create_index(
        "ix_match_corrections_event", "match_corrections", ["school_id", "event_id"]
    )
    op.create_index(
        "ix_match_corrections_student", "match_corrections", ["school_id", "student_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_match_corrections_student", table_name="match_corrections")
    op.drop_index("ix_match_corrections_event", table_name="match_corrections")
    op.drop_index("ix_match_corrections_media", table_name="match_corrections")
    op.drop_table("match_corrections")
