# 0003 — Monorepo structure: FE + BE + ML service, 3 images

**Date:** 2026-06-30
**Status:** Accepted (scaffolding pending owner approval — see [0001](0001-adopt-decision-log-and-working-rules.md) plan-first rule)

## Context

The repo started as the ML service only. The owner now wants a single repo holding three deployables, each built into its own Docker image:

1. **Frontend** — Next.js (Node).
2. **Backend (BE)** — Python + FastAPI. This is the "core system" referenced in the requirements: it handles uploads, storage, notifications, consent, and distribution UX; it enqueues inference jobs to the ML service and calls the ML service's enrollment API.
3. **ML service** — Python + FastAPI + workers, as specified in `ml-service-requirements.md` / `ml-service-architecture.md`.

## Decisions

- **Single repo, 3 images.** One Dockerfile per deployable.
- **Python tooling: `uv`**, in **workspace** mode — one root `pyproject.toml` + one `uv.lock` shared by the Python members (`backend`, `ml_service`), with shared code factored into `packages/` later.
- **Directory layout** (`services/` + `frontend/`):

  ```
  repo/
  ├─ pyproject.toml      # uv workspace root
  ├─ uv.lock
  ├─ frontend/           # Next.js  → image 1
  ├─ services/
  │  ├─ backend/         # FastAPI  → image 2  (src/backend/)
  │  └─ ml_service/      # FastAPI + workers → image 3 (src/ml_service/)
  ├─ packages/           # shared Python libs (added when needed)
  └─ docker-compose.yml
  ```

- **ML service relocation.** The `ml_service` package tree from architecture §5 moves under `services/ml_service/src/ml_service/`. Internal module structure and all invariants are unchanged — only the location changes, and it adopts a `src/` layout.
- **BE ↔ ML boundary.** BE is the only caller of the ML service's HTTP enrollment API and the producer of inference jobs onto the queue. The ML service does not call BE.

## Why

- `uv` workspaces give one lockfile and fast, reproducible installs across the two Python services without per-service dependency drift.
- `services/` vs `frontend/` keeps the Node toolchain cleanly separate from the Python workspace and preserves the existing `ml_service` package name.

## Open (to confirm before/while scaffolding)

- BE framework details beyond "FastAPI" (DB, auth) — defer until BE work starts.
- Whether FE talks to BE only, or also directly to the ML service (assumption: FE → BE only).
