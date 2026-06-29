# 0004 — Scaffold the monorepo (uv workspace + 3 images)

**Date:** 2026-06-30
**Status:** Accepted

## Context

[0003](0003-monorepo-structure.md) settled the structure. The owner approved
building the full scaffold now: Python 3.12, Postgres + Redis included in
docker-compose, all three components as runnable shells.

## What was built

- **Root uv workspace** — `pyproject.toml` (`members = ["services/*", "packages/*"]`),
  shared dev group (ruff, pytest, pytest-asyncio, mypy, httpx), ruff/mypy/pytest
  config. `.python-version` pins 3.12. `uv.lock` generated.
- **`services/ml_service/`** — FastAPI app factory (`/healthz`, `/readyz`), the
  architecture §5 package skeleton (`domain`, `orchestration`, `adapters`, `api`,
  `workers`, `wiring`, `observability`) as documented empty packages, a worker
  entrypoint stub, a `wiring/settings.py` stub, health test, Dockerfile.
- **`services/backend/`** — FastAPI app factory (`/healthz`, `/readyz`), settings
  stub (holds `ml_service_url`), health test, Dockerfile.
- **`frontend/`** — Next.js (TypeScript, App Router, ESLint, no Tailwind) via
  `create-next-app`; `next.config.ts` set to `output: "standalone"`; multi-stage
  Dockerfile + `.dockerignore`.
- **`docker-compose.yml`** — all 3 images + Postgres 16 + Redis 7 with healthchecks.
- Root `README.md`; `.gitignore` extended for Node.

## Decisions made while scaffolding

- **No `make`/`just` task runner** — not installed on the Windows dev box; commands
  are documented in `README.md` / `CLAUDE.md` instead.
- **pytest `--import-mode=importlib`** so same-named test files (`test_health.py`)
  coexist across workspace members without `__init__.py` collisions.
- **Python Dockerfiles build from repo root context** (need root `pyproject.toml`
  + `uv.lock`); frontend builds from `./frontend`.
- **Postgres/Redis compose credentials are throwaway dev values** (`app`/`app`),
  documented as not for reuse. Not stored in memory.

## Verification

- `uv sync --all-packages` succeeds; `uv run pytest` → 4 passed (2 per service).
- `docker compose config` validates.
- **Not** verified: actual `docker build` / `compose up` — Docker Desktop was not
  running at scaffold time. Dockerfiles are written but unbuilt; build them once
  the daemon is up.

## Not done (per plan: shells only)

No business logic, no domain models/ports, no adapters, no DB schema, no FE pages
beyond the create-next-app default.
