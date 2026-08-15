"""events.processing_status add 'failed'

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-09

BP19a (decisions/0069) — a dead-lettered event job used to strand the event at
``processing`` forever (the DLQ had no consumer). Now the ML worker's DLQ consumer marks
such an event ``failed`` (visible + retryable via Process). Widens the
``ck_events_processing_status`` CHECK from ``('not_started','queued','processing',
'completed')`` to add ``'failed'``. Mirrors ``0009`` (which added ``'failed'`` to media) +
``backend.db.models.Event`` + the ``EventProcessingStatus`` domain enum.

Reversible **only while no event is ``'failed'``** — the downgrade re-imposes the 4-value
CHECK, which fails if any failed event exists. Backend chain (alembic_version_backend);
touches only the backend-owned ``events`` table (the ML worker writes the value directly,
so this must be applied before deploying the worker change).
"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CK = "ck_events_processing_status"


def upgrade() -> None:
    op.drop_constraint(_CK, "events", type_="check")
    op.create_check_constraint(
        _CK,
        "events",
        "processing_status IN "
        "('not_started', 'queued', 'processing', 'completed', 'failed')",
    )


def downgrade() -> None:
    op.drop_constraint(_CK, "events", type_="check")
    op.create_check_constraint(
        _CK,
        "events",
        "processing_status IN ('not_started', 'queued', 'processing', 'completed')",
    )
