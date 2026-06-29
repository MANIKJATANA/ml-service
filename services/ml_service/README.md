# ML Service

Face enrollment + inference for photo distribution. Hexagonal architecture —
see the repo-root `ml-service-requirements.md` and `ml-service-architecture.md`
for the binding specs.

## Layout

`src/ml_service/` — `domain/` (pure), `orchestration/`, `adapters/`, `api/`,
`workers/`, `wiring/`, `observability/`. Layering rule: `domain` and
`orchestration` import no third-party ML/IO libraries.

## Run (from repo root)

```bash
uv run uvicorn ml_service.api.main:app --reload    # API, http://localhost:8000
uv run python -m ml_service.workers.inference_worker
uv run pytest services/ml_service
```

Status: scaffold — health endpoints only, no business logic yet.
