# Photo Distribution Platform (monorepo)

One repository, three deployable images:

| Component | Path | Stack | Port (local) |
|---|---|---|---|
| Frontend | `frontend/` | Next.js (TS, App Router) | 3000 |
| Backend (core system) | `services/backend/` | FastAPI | 8001 |
| ML service | `services/ml_service/` | FastAPI + workers | 8000 |

Python is managed with [`uv`](https://docs.astral.sh/uv/) in **workspace** mode
(one `uv.lock` for both Python services). Specs live at the repo root:
`ml-service-requirements.md`, `ml-service-architecture.md`. Architecture
decisions are logged in `decisions/`. Contributor guide: `CLAUDE.md`.

## Prerequisites

`uv`, Node 20+ / npm, Docker (for images). Python 3.12 is fetched by `uv`.

## Common commands

```bash
# Python (run from repo root)
uv sync --all-packages                 # install all workspace deps
uv run pytest                          # run all Python tests
uv run pytest services/ml_service      # one service
uv run ruff check . && uv run mypy .   # lint + type-check
uv run uvicorn ml_service.api.main:app --reload          # ML service :8000
uv run uvicorn backend.main:app --reload --port 8001     # backend  :8001

# Frontend
cd frontend && npm install && npm run dev                 # :3000

# Everything via Docker (needs Docker Desktop running)
docker compose up --build
```

Status: scaffold — runnable shells with health endpoints (`/healthz`, `/readyz`),
no business logic yet.

> The Postgres/Redis credentials in `docker-compose.yml` are throwaway local-dev
> values only — never reuse them anywhere real.
