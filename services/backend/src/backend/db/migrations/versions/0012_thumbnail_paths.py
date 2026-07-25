"""thumbnail_paths

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-25

Adds the BP17 stored-thumbnail paths (decisions/0056): a nullable ``media.thumbnail_path``
and ``students.reference_photo_thumbnail_path``. On register/create the backend downscales
each uploaded image to a stored JPEG sibling and records its path here; the download endpoints
serve the thumbnail path for ``?size=thumb`` (falling back to the full-res path when NULL —
pre-BP17 rows + video). Display-only: the ML pipeline always reads the full-res path.

Backend chain (alembic_version_backend). Additive — two nullable columns, no table/constraint
change, no ML chain. Fully reversible (the down drops exactly what the up added).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media", sa.Column("thumbnail_path", sa.String(), nullable=True))
    op.add_column(
        "students",
        sa.Column("reference_photo_thumbnail_path", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("students", "reference_photo_thumbnail_path")
    op.drop_column("media", "thumbnail_path")
