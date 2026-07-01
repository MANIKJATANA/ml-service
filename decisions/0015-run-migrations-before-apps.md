# 0015 — Run DB migrations before the apps start

**Date:** 2026-07-02
**Status:** Accepted

## Context

The owner asked that the run command apply any pending DB migrations *first*, then
bring the apps up — and confirmed that **local runs on Docker too**, so there is no
separate "local runtime": the same real adapters run everywhere. Migrations must
therefore be part of the normal `docker compose` / `up.ps1` flow, not a manual
step someone might forget. (This pulls the migration step forward from Phase 4.)

## Decision

- Add a one-shot **`migrate`** service to `docker-compose.yml` (built from the
  ml-service image) that runs `alembic -c services/ml_service/alembic.ini upgrade
  head`, depends on Postgres being healthy, and exits. It reads
  `ML_DATABASE_URL` (`postgresql+asyncpg://…`).
- `ml-service` now `depends_on: migrate: condition: service_completed_successfully`,
  so a plain `docker compose up` applies migrations before the app starts.
- `scripts/up.ps1` runs `docker compose run --rm [--build] migrate` explicitly
  between the backing services and the apps (the apps come up with `--no-deps`, so
  the compose dependency alone wouldn't trigger it there). It aborts if migrations
  fail.
- The migration binary and files are already in the ml-service image (alembic is a
  runtime dep; `alembic.ini` uses `%(here)s` so it resolves from `/app`). No model
  bundle is needed to migrate, so this works with the current (pre-Phase-4)
  Dockerfile.

## Why

- Schema is always current before code that assumes it runs — no "table does not
  exist" on first boot, and no manual migrate step to forget.
- Same real adapters in local Docker and prod; the `local_fs`/`inproc`/`opencv`
  adapters remain **test-only** (never wired into any compose service).

## Alternatives rejected

- **Migrating on app startup (in-process)** — bypasses the "schema only via
  migrations, app assumes it" separation and races across replicas.
- **Manual `alembic upgrade head`** — easy to forget; not reproducible in CI/compose.
