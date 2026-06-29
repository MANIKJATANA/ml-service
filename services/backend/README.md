# Backend (core system)

FastAPI service that owns uploads, storage, notifications, consent, and
distribution. It calls the ML service's enrollment API and enqueues inference
jobs onto the queue.

## Run (from repo root)

```bash
uv run uvicorn backend.main:app --reload --port 8001    # http://localhost:8001
uv run pytest services/backend
```

Status: scaffold — health endpoints only.
