"""initial ML-service schema: matches, school_thresholds, student_reference_photos

Revision ID: 0001
Revises:
Create Date: 2026-07-02

Mirrors ml_service.db.models and the req §10 data contracts.
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
        "matches",
        sa.Column("match_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("school_id", sa.String(), nullable=False),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("media_id", sa.String(), nullable=False),
        sa.Column("media_type", sa.String(), nullable=False),
        sa.Column("confidence_score", sa.Float(), nullable=False),
        sa.Column("bbox", postgresql.JSONB(), nullable=True),
        sa.Column("frame_timestamp_ms", sa.Integer(), nullable=True),
        sa.Column("needs_review", sa.Boolean(), nullable=False),
        sa.Column("embedding_model_version", sa.String(), nullable=False),
        sa.Column("detector_model_version", sa.String(), nullable=False),
        sa.Column("threshold_used", sa.Float(), nullable=False),
        sa.Column("gap_threshold_used", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("match_id"),
        sa.UniqueConstraint(
            "media_id", "student_id", name="uq_matches_media_student"
        ),
    )
    op.create_index(
        "ix_matches_school_event", "matches", ["school_id", "event_id"]
    )
    op.create_index(
        "ix_matches_school_student", "matches", ["school_id", "student_id"]
    )

    op.create_table(
        "school_thresholds",
        sa.Column("school_id", sa.String(), nullable=False),
        sa.Column("match_confidence_threshold", sa.Float(), nullable=True),
        sa.Column("gap_threshold", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("school_id"),
    )

    op.create_table(
        "student_reference_photos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("school_id", sa.String(), nullable=False),
        sa.Column("student_id", sa.String(), nullable=False),
        sa.Column("photo_uri", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_srp_school_student",
        "student_reference_photos",
        ["school_id", "student_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_srp_school_student", table_name="student_reference_photos")
    op.drop_table("student_reference_photos")
    op.drop_table("school_thresholds")
    op.drop_index("ix_matches_school_student", table_name="matches")
    op.drop_index("ix_matches_school_event", table_name="matches")
    op.drop_table("matches")
