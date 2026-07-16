"""students.reference_photo_path nullable

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-16

BP7d — CSV bulk import creates students from name+email only (no photo), so a student can
exist WITHOUT a reference photo (``enrollment_status='pending'`` until one is added). Makes
``students.reference_photo_path`` nullable. Mirrors ``backend.db.models.Student``.

Reversible **only while no row has a NULL path** — the downgrade re-imposes NOT NULL, which
fails if any photoless (bulk-imported) student exists. That's expected: don't downgrade past
a bulk import without first backfilling/removing photoless rows.

Backend chain (alembic_version_backend). Touches only the backend-owned ``students`` table.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "students",
        "reference_photo_path",
        existing_type=sa.String(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "students",
        "reference_photo_path",
        existing_type=sa.String(),
        nullable=False,
    )
