# 0006 — Temporary end-to-end wiring demo

**Date:** 2026-06-30
**Status:** Accepted — **TEMPORARY, to be removed**

## Context

Before building real features, the owner wanted to prove the plumbing works:
FE → BE, BE → ML service over **both** HTTP API and Redis queue, with Postgres
writes from both BE and the ML service.

## What was added (all marked TEMP in code)

- **Postgres** `demo_events(id, source, detail, created_at)` — created on startup
  by both services (`CREATE TABLE IF NOT EXISTS`).
All HTTP endpoints live under `/temp` (migrated from `/demo`).

- **Backend** `backend/demo.py` + router (prefix `/temp`):
  - `POST /temp/run` → writes a `backend` row, calls ML service `POST /temp/ping`
    over HTTP, and `XADD`s a job to the Redis stream `demo-jobs`.
  - `GET /temp/events` → lists recent rows.
- **ML service** `ml_service/demo.py` + router (prefix `/temp`):
  - `POST /temp/ping` → writes an `ml-service-api` row.
  - background Redis consumer (started in the app lifespan) reads `demo-jobs` and
    writes an `ml-service-redis` row per job.
- **Frontend** `app/api/temp/route.ts` (server-side proxy to the backend, so no
  CORS) and the demo UI at `app/temp/page.tsx` (route `/temp`) with a "Run demo"
  button + events table. The home page (`app/page.tsx`) is a clean placeholder —
  the demo does NOT render on `/`.
- **Deps:** backend += httpx, redis, psycopg[binary]; ml_service += redis,
  psycopg[binary]. **Compose env:** `DATABASE_URL`, `REDIS_URL`, `ML_SERVICE_URL`
  (backend + ml-service) and `BACKEND_URL` (frontend).
- **mypy:** `backend.demo` / `ml_service.demo` set to `ignore_errors` (throwaway).

## Verification (real Docker, both via backend directly and via the FE proxy)

A `/temp/run` produced three Postgres rows each time:
`backend`, `ml-service-api`, `ml-service-redis` — confirming the HTTP path, the
Redis path, and DB writes from both services. ruff + mypy + pytest all green.

## Removal checklist (when replacing with real features)

- Delete `backend/demo.py`, `ml_service/demo.py`, `frontend/app/temp/`,
  `frontend/app/api/temp/`. (Home `frontend/app/page.tsx` is a normal placeholder,
  not demo code — leave or replace as needed.)
- Remove the demo router/lifespan wiring from both `main.py` files.
- Drop the TEMP deps + compose env + the `demo_events` table + the mypy override.
