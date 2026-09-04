"""platform_config.template_name

Revision ID: 0026
Revises: 0025
Create Date: 2026-09-04

Adds ``platform_config.template_name`` — the approved WhatsApp message template the non-interim
send uses. Moved here from the (now-removed) per-school ``school_whatsapp_config`` because schools
no longer configure WhatsApp; the platform admin owns it all at Platform → WhatsApp (0099). Mirrors
``backend.db.models.PlatformConfig``.

Additive + nullable (existing rows adopt NULL → a send fails clearly, "set the approved template at
Platform → WhatsApp", until one is set). Backend chain (alembic_version_backend); touches only the
existing backend-owned ``platform_config`` table — no ML chain, no data migration. The dormant
``school_whatsapp_config`` table is deliberately NOT dropped (no destructive migration). Fully
reversible (the down drops the column). Verified up→down→up on a throwaway Postgres.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "platform_config",
        sa.Column("template_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("platform_config", "template_name")
