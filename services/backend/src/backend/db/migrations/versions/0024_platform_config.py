"""platform_config

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-02

Adds the W-live-test platform-wide config singleton. Mirrors backend.db.models.PlatformConfig.

A backend-owned, ONE-ROW config table (the application always reads/writes the constant key
``"platform"``): platform-admin-only. Two features live here.

- ``meta_access_token`` is a SECRET stored in the DB per owner decision (a UI-editable Meta
  Cloud API temp token). It is NEVER returned in full (responses expose only ``token_set`` +
  ``token_last4``), NEVER logged, and has an ENV fallback (``BE_WHATSAPP_META_ACCESS_TOKEN``) —
  the DB value takes precedence when set, else the env var is used.
- ``interim_test_number`` + ``interim_mode`` drive the interim free-form send (a text intro + N
  real photos to a hardcoded test number) while the approved-template flow is not yet live.

``id`` is the PK (a String singleton, always ``"platform"``); the token/number are nullable;
``interim_mode`` defaults false (opt-in). Read by PK, so no extra index and no CHECK.

Backend chain (alembic_version_backend). Touches only a new backend-owned table — no ML chain,
no change to existing tables. Fully reversible (the down drops the table). Verified up→down→up on
a throwaway Postgres (``wlive_migtest``).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_config",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("meta_access_token", sa.String(), nullable=True),
        sa.Column("interim_test_number", sa.String(), nullable=True),
        sa.Column(
            "interim_mode",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        # updated_at: the ORM model also declares onupdate=func.now() (applied client-side); the
        # upsert adapter additionally sets updated_at=func.now() explicitly, so the column is
        # always bumped. No server-side trigger is needed.
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("platform_config")
