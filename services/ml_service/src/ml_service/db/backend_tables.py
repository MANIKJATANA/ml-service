"""Definitions of the backend-owned ``events``/``media`` tables the worker touches.

The **single coupling point** to the backend's schema (decisions/0027). The backend owns
+ migrates these tables; the ML worker **reads** the event's photo roster and **writes**
the status columns (event ``processing``/``completed``; each photo ``completed``) — that
is how job status flows, so the backend needs no poller. They live on their **own**
``MetaData`` — deliberately NOT the ML ``Base`` — so ML Alembic never manages them. Both
services target the same ``app`` Postgres, so the ML sessionmaker reads/writes directly;
no cross-service HTTP.

Only the columns the worker touches are declared. A Phase-7 ``information_schema``
contract test asserts they still exist, so a backend migration that renames/drops one
fails ML CI loudly rather than at runtime.
"""

from __future__ import annotations

from sqlalchemy import Column, DateTime, MetaData, String, Table
from sqlalchemy.dialects.postgresql import UUID

# Separate metadata: these tables are backend-owned (never in the ML Base.metadata).
backend_metadata = MetaData()

media = Table(
    "media",
    backend_metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column("school_id", UUID(as_uuid=True), nullable=False),
    Column("event_id", UUID(as_uuid=True), nullable=False),
    Column("storage_path", String, nullable=False),
    Column("media_type", String, nullable=False),
    Column("processing_status", String, nullable=False),  # 'pending' | 'completed'
    Column("completed_at", DateTime(timezone=True), nullable=True),
)

events = Table(
    "events",
    backend_metadata,
    Column("id", UUID(as_uuid=True), nullable=False),
    Column("school_id", UUID(as_uuid=True), nullable=False),  # tenant-scope the writes
    # 'not_started' | 'queued' | 'processing' | 'completed' | 'failed' — the worker writes
    # 'processing'/'completed' and (BP19a, the DLQ consumer) 'failed'; must stay in lockstep
    # with the backend's EventProcessingStatus + ck_events_processing_status.
    Column("processing_status", String, nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=True),
)
