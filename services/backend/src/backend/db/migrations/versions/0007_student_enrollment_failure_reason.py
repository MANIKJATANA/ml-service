"""student enrollment_failure_reason

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-16

Adds the BP7b reference-photo quality-feedback column (decisions/0045). A nullable
``enrollment_failure_reason`` on ``students`` records *why* an enrollment ``failed`` —
one of ``no_face`` / ``ml_unavailable`` / ``error`` — so staff get a specific
explanation + fix instead of a bare "Failed". Null unless ``enrollment_status='failed'``;
cleared on a successful (re-)enroll. Mirrors ``backend.db.models.Student``.

Backend chain (alembic_version_backend). Touches only the backend-owned ``students``
table — no ML chain, no ML change.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("enrollment_failure_reason", sa.String(), nullable=True),
    )
    op.create_check_constraint(
        "ck_students_enrollment_failure_reason",
        "students",
        "enrollment_failure_reason IS NULL OR enrollment_failure_reason IN "
        "('no_face', 'ml_unavailable', 'error')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_students_enrollment_failure_reason", "students", type_="check"
    )
    op.drop_column("students", "enrollment_failure_reason")
