# 0007 — All DB schema changes go through migrations

**Date:** 2026-07-01
**Status:** Accepted

## Context

The schema for the demo `demo_events` table (and any future tables) was created
ad-hoc rather than through a tracked migration. As real features land, schema
drift between environments and untracked changes in application code become a
correctness and review hazard.

## Decision

Every change to the database schema — creating/altering/dropping tables,
columns, indexes, constraints, or types — must be a versioned migration file in
the migrations folder. Schema changes must **not** be made directly in
application code (e.g. inline `CREATE TABLE`/`ALTER TABLE` on startup).
Application code may only assume the schema that a migration has already
established.

Added as a working rule in `CLAUDE.md`.

## Why

- One reviewable, ordered history of how the schema evolved.
- Reproducible, identical schema across dev/CI/prod.
- Separates "change the shape of the data" from "use the data" — code reviews
  and rollbacks stay clean.

## Notes

- The concrete migration tool is not yet chosen (Alembic is the natural fit
  given SQLAlchemy 2.x async per the architecture doc). Pick and wire it when
  the first real table lands; record that as its own decision.
- The existing **TEMP** `demo_events` table (decisions/0006) is exempt — it is
  scheduled for removal, not migration.
