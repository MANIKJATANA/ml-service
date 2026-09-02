"""platform_config.sender_number

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-03

Adds ``platform_config.sender_number`` — the Meta sender phone-number ID, now DB-controlled so a
platform admin can change WHICH number sends (and the access token + interim number) from the UI
without a restart. Mirrors ``backend.db.models.PlatformConfig``.

Additive + nullable (existing rows adopt NULL). The DB is the SOLE source of the sender ID (0098:
NO env fallback — an unset value resolves to "" so a send fails clearly rather than silently using
a stale env value). Backend chain (alembic_version_backend); touches only the existing
backend-owned ``platform_config`` table — no ML chain, no data migration. Fully reversible (the down
drops the column). Verified up→down→up on a throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_config",
        sa.Column("sender_number", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_config", "sender_number")
