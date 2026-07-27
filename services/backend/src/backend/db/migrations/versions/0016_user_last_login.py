"""user_last_login

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-27

Adds the BP14 sign-in signal (decisions/0062): a nullable ``users.last_login_at`` timestamp,
stamped ``now()`` on each successful login (never on token refresh — that isn't an interactive
sign-in). Powers the "how many students have ever signed in" sign-in rate on the school
analytics page and the per-school adoption funnel's signed-in count on the estate view.

Backend chain (alembic_version_backend). Additive — one nullable column, no table/constraint
change, no ML chain. No backfill (past logins were never recorded, so the rate is forward-looking
from launch). Fully reversible (the down drops exactly what the up added).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
