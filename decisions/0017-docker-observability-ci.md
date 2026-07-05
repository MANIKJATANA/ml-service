# 0017 — Phase 4: Docker, observability, CI, and TEMP-demo removal

**Date:** 2026-07-06
**Status:** Accepted

## Context

Phases 1–3 delivered the domain core, real adapters + migrations, and the
wiring/API/worker. Phase 4 makes the service deployable and operable, wires the
layering invariant into CI, and removes the temporary end-to-end wiring demo
(decisions/0006) now that real paths exist.

## Decisions

### One image, three roles + model baking

`services/ml_service/Dockerfile` builds a single image runnable as **API**,
**worker**, or **migrate** (the container `command` selects the role); all three
compose services share one `image:` tag so it is built once. The InsightFace
`buffalo_l` bundle is **baked at build time** — the Dockerfile fetches the
official release zip with the Python stdlib and extracts the `.onnx` files to
`/models/buffalo_l`. Baking via the stdlib (not the insightface download API)
keeps it independent of the resolved insightface version (locked at 1.0.1, a
pure-python wheel). `libgl1`/`libglib2.0-0` are installed for opencv (pulled in
transitively) at runtime.

### CPU default, GPU as a config swap

Base image is CPU (`onnxruntime` + `faiss-cpu`). GPU is documented as a
base-image + `onnxruntime-gpu` + providers/ctx_id swap (docs/08-deployment.md),
not a code change — Windows Docker Desktop has no GPU passthrough, so dev stays
CPU.

### Compose: `ml-worker` + shared FAISS volume

Added an `ml-worker` service (same image, worker command). A named `faiss` volume
is mounted into **both** the API (writes on enroll) and the worker (reads on
inference) — the shared-volume dev form of the index store (architecture §7).
`ml-service` and `ml-worker` share one env block via a YAML anchor so config can't
drift. Both wait on the one-shot `migrate` (decisions/0015). `scripts/up.ps1`
now includes `ml-worker` in the foreground app set.

### Observability (requirements §13)

`observability/{metrics,logging,tracing}.py`:
- **Metrics** — one Prometheus counter per §13 signal + a `processing_latency_ms`
  histogram, labelled `school_id` + detector/embedder versions only (never
  `student_id`/`media_id`). `record_job_outcome` matches the runner's
  `OutcomeSink` signature and is wired as `on_outcome`; the API serves the default
  registry at `GET /metrics`.
- **Logging** — structlog, JSON by default (`ML_LOG_JSON`), bridging stdlib
  logging; configured from both the API lifespan and worker entrypoint.
- **Tracing** — OTel, **opt-in** via `ML_OTEL_EXPORTER_OTLP_ENDPOINT`; no-op
  otherwise. v1 spans the **service-call boundary** (worker `inference.process`)
  rather than every port call, to keep the pure layers import-free. Per-adapter
  spans via a container-level tracing proxy are **deferred**.

### CI + local gate

`.github/workflows/ci.yml`: a `check` job (ubuntu) runs `uv sync --all-packages`,
ruff, mypy, an explicit layering grep, and pytest — Linux installs the (pure-py
wheel) heavy deps; gated model/DB/Redis tests skip. A `docker-build` job proves
the image builds and the model bake succeeds. `scripts/check.ps1` mirrors the
`check` job for local Windows runs.

### TEMP wiring demo removed (decisions/0006 checklist)

Deleted `ml_service/demo.py`, `backend/demo.py`, `frontend/app/temp/`,
`frontend/app/api/temp/`; removed the demo router/lifespan wiring from both
`main.py` files; dropped the TEMP deps (`httpx`/`redis`/`psycopg[binary]` from
backend, `psycopg[binary]` from ml_service), the `backend.demo`/`ml_service.demo`
mypy override, and the TEMP compose env. The `demo_events` table was never a
migration (runtime `CREATE TABLE IF NOT EXISTS`) — it simply stops being created.

## Review fixes (non-obvious gotchas)

- **`libgomp1` in the image.** `faiss-cpu` (and onnxruntime) dlopen `libgomp.so.1`
  (OpenMP), absent on `python:3.12-slim`; without it `import faiss` fails at
  runtime in both the API and worker. Installed alongside `libgl1`/`libglib2.0-0`.
- **structlog stdlib bridge.** The worker logs its `JobOutcome` via stdlib
  `logging` with `extra={...}`. The `ProcessorFormatter.foreign_pre_chain` needs
  `structlog.stdlib.ExtraAdder()` or those fields are silently dropped, and
  `format_exc_info` in the processor chain to render `log.exception` tracebacks.
  Guarded by a `test_observability.py` test that inspects rendered JSON.

## Consequences

- The stack is deployable: `docker compose up --build` → migrations, API
  (`/healthz`, `/readyz`, `/metrics`), and `ml-worker`, with `buffalo_l` in the
  image. The layering invariant fails the build if violated.
- **Unverified on this host:** the Docker build + model bake and the InsightFace
  runtime path (insightface 1.0.1) have not been executed here (Windows, no Docker
  run); they run in CI's `docker-build` job and on a Docker host. Surfaced for the
  Phase 4 review.
- FE/BE lose their only wired path (they are shells again) until real features
  land — intended per 0006.
