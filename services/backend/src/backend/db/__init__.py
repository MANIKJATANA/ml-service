"""Backend DB layer: declarative base, ORM models, engine/session, migrations.

Backend-owned tables only. The ML-owned tables/views the backend reads live in
``ml_read.py`` (added in a later phase) as read-only Core tables, deliberately kept
out of ``Base.metadata`` so the backend Alembic chain never manages them.
"""
