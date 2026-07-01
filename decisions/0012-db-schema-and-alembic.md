# 0012 — ML metadata schema + Alembic (async) migrations

**Date:** 2026-07-02
**Status:** Accepted

## Context

Phase 2 needs the ML service's own metadata tables (req §10) and a migration tool.
The working rules mandate that **all** schema changes go through versioned
migration files ([0007](0007-db-migrations-in-migration-folder.md)); application
code may only assume a schema a migration already established.

## Decision

- **Tables (ML-owned Postgres), created by `0001_initial`:**
  - `matches` — req §10.1. Unique `(media_id, student_id)` (idempotency, NFR-5);
    indexes `(school_id, event_id)` and `(school_id, student_id)`. `match_id` is a
    client-side UUID (no `pgcrypto` needed); `created_at` has a `now()` server
    default; `bbox` is JSONB; `media_type` is stored as text.
  - `school_thresholds` — req §10.2, the two nullable override columns. **ML owns
    this table** rather than reading the core's `schools` table, preserving tenant
    isolation and the "ML never calls BE" rule. Null/missing → global default.
  - `student_reference_photos` — backs student-id enrollment
    ([0009](0009-enrollment-contract.md)); indexed `(school_id, student_id)`.
- **Alembic, async (asyncpg).** `env.py` reads the DB URL from `ML_DATABASE_URL`
  (never a committed file or the ini) and targets `ml_service.db.base.Base`. The
  ini uses `%(here)s` so it runs from any CWD. Migrations are **hand-authored**
  and reviewed; autogenerate is only a drafting aid.
- **ORM models** (`db/models.py`) mirror the migration exactly and are used by the
  repository adapters. `Base.metadata.create_all` is used **only** in test
  fixtures, never in application code.

## Why

- Satisfies the migrations rule and req §10 constraints; keeps ML's schema private
  and decoupled from the core.
- Async Alembic keeps a single driver (asyncpg) across the app and migrations, so
  the throwaway TEMP `psycopg` dep can still be removed in Phase 4.

## Alternatives rejected

- **Reading the core's `schools` table for thresholds** — couples ML to BE's
  schema; violates isolation.
- **`metadata.create_all` at startup** — bypasses versioned migrations (0007).
- **Sync Alembic via psycopg** — would retain a dep slated for removal.
