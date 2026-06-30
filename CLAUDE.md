# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules (always follow)

- **Record every decision.** Any change or non-trivial decision gets a dated entry in `decisions/` (see `decisions/README.md` for the format). Update the index there.
- **Keep this file current.** When architecture, commands, or conventions change, update CLAUDE.md in the same change.
- **Never commit or push on your own.** Make and verify changes, but do not run `git commit`, `git push`, or open PRs until the user explicitly asks. Leave changes staged/unstaged for them to review.
- **Self-review.** After making changes, review your own work and fix the issues you introduced before reporting done.
- **All DB schema changes go through migrations.** Any change to the database schema (tables, columns, indexes, constraints, types) must be a versioned migration file in the migrations folder — never an ad-hoc schema change made directly in application code. Application code may only assume the schema a migration has already established.
- **Never read `.env` files** (or any secrets files), and never store secrets in memory or in code.

## Repo shape: monorepo, 3 Docker images

This is **one repo** that builds **three images** (see [decisions/0003](decisions/0003-monorepo-structure.md)):

| Image | Path | Stack | Role |
|---|---|---|---|
| Frontend | `frontend/` | Next.js (Node) | UI |
| Backend (BE) | `services/backend/` | Python + FastAPI | The "core system": uploads, storage, notifications, distribution; calls the ML service's enrollment API and enqueues inference jobs |
| ML service | `services/ml_service/` | Python + FastAPI + workers | Face enrollment/inference, as specced below |

Python is managed with **`uv` in workspace mode** — one root `pyproject.toml` + one `uv.lock` shared by the Python members (`backend`, `ml_service`); shared Python code goes in `packages/`. The Next.js frontend is a separate Node package. BE is the only caller of the ML service; the ML service never calls BE.

The structure above is **scaffolded** (see [decisions/0004](decisions/0004-scaffold-monorepo.md)): each service is a runnable shell with `/healthz` + `/readyz` and a passing health test; no business logic yet.

> **TEMP wiring demo present** (see [decisions/0006](decisions/0006-temporary-wiring-demo.md)): `demo.py` modules, `/temp/*` routes, a `demo_events` table, the FE demo at `app/temp/page.tsx` (route `/temp`) + `app/api/temp/`, and TEMP deps/env exist only to prove FE→BE→ML (HTTP + Redis) + Postgres wiring. The home page `/` is a clean placeholder. Everything is marked `TEMP` — delete it (removal checklist in 0006) when real features land.

## Commands

Run Python commands from the repo root (uv workspace). `uv` fetches Python 3.12 itself.

```bash
uv sync --all-packages              # install all workspace deps (creates .venv)
uv run pytest                       # all Python tests
uv run pytest services/ml_service   # a single service's tests
uv run ruff check . && uv run mypy .
uv run uvicorn ml_service.api.main:app --reload          # ML service  :8000
uv run uvicorn backend.main:app --reload --port 8001     # backend     :8001
cd frontend && npm install && npm run dev                # frontend    :3000
docker compose up --build           # all 3 images + Postgres + Redis (needs Docker running)
./scripts/up.ps1                    # helper: Postgres+Redis detached (stay up), apps in foreground; Ctrl+C stops only the apps
```

Helper scripts live in `scripts/` (see `scripts/README.md`).

Notes for future instances:
- The Python Dockerfiles build from the **repo root** context (they need root `pyproject.toml` + `uv.lock`); only the frontend builds from `./frontend`.
- pytest uses `--import-mode=importlib` so same-named test files coexist across services — don't add `__init__.py` to `tests/` dirs.
- New Python deps go in the **service's** `pyproject.toml`; shared dev tools in the root `[dependency-groups] dev`. Re-run `uv sync --all-packages` after.

## Status: scaffolded, no business logic yet

The repo is git-initialized (`main`) with a secrets-safe `.gitignore`. The two ML-service specs are the binding source of truth:

- `ml-service-requirements.md` — locked v1 requirements (the "what"). Source of truth for functional/non-functional requirements, locked decisions (§8), interface contracts (§9), and data contracts (§10).
- `ml-service-architecture.md` — v1 architecture (the "how"). Source of truth for module layout (§5), adapter choices + versions (§6), and the FAISS index lifecycle (§7).

When implementing, treat both docs as binding. The architecture doc's §5 module tree is the intended layout (relocated under `services/ml_service/src/ml_service/`); §6's adapter table fixes the initial library choices and versions. If a code change contradicts either doc, surface the conflict rather than silently diverging.

## What this service is

A multi-tenant face-recognition service for distributing event photos/videos to the students who appear in them. Two pipelines that share one embedding model version but are otherwise independent:

- **Enrollment** (synchronous HTTP): detect face in reference photos → embed → upsert into a per-school vector index.
- **Inference** (async, queue-driven workers): fetch media → (video) extract frames at fixed FPS → detect → embed → search the school's index → apply threshold/gap decision → dedupe → persist match records.

## Architecture: hexagonal (ports and adapters)

The design exists to satisfy NFR-1/NFR-2 (swap ML stack or storage by config alone). The whole structure depends on strict layering:

- `domain/` — pure, imports no third-party libs. Models, the 8 `Protocol` ports (req §9), and the pure `apply_threshold_and_gap()` decision function.
- `orchestration/` — `EnrollmentService` / `InferenceService`. Imports only `domain`.
- `adapters/` — one subpackage per port; the only place concrete libs (faiss, insightface, azure, redis, sqlalchemy) are imported.
- `api/`, `workers/`, `wiring/` — the only modules allowed to import adapters. `wiring/container.py` builds concrete adapters from config via a name→class registry and injects them into the services.

**Layering invariant (wire into CI):** no concrete ML/IO library may be imported in `domain/` or `orchestration/`. The doc's acceptance test:
```
grep -r "import faiss\|import cv2\|import insightface\|import boto3" ml_service/domain ml_service/orchestration
```
must return nothing. The API and worker are thin shells — both build a job context and call the same service code paths.

## Correctness invariants (do not break these)

These come straight from the specs and are the easy things to get subtly wrong:

- **Tenant isolation (NFR-3, FR-I4):** all matching is strictly within one `school_id`. Enforced at the `VectorIndex` interface. There is no cross-school search in v1.
- **Threshold resolution is once per job, not per face.** Resolve `Thresholds` into the job context, pass it as a value into the pure decision function. Per-school value with global-default fallback when null (req §6.1).
- **Reproducibility (NFR-4):** each match record persists `embedding_model_version`, `detector_model_version`, `threshold_used`, `gap_threshold_used` — the values actually used at decision time, not re-read at write time.
- **Two-layer idempotency (NFR-5):** in-memory worker dedupe keyed on `(student_id, media_id)` first; DB unique constraint on `(media_id, student_id)` as the second line of defence. `save_batch` is the only DB write path and uses `INSERT ... ON CONFLICT` where higher confidence wins.
- **Decision logic (req §6.2):** top-K=2. ≥threshold filter; 0 → unknown (log only, no record, FR-I8); 1 → emit; 2 → emit top-1 alone if `(top1-top2) > gap`, else emit both with `needs_review=true`.
- **Embedding convention:** 512-dim ArcFace, L2-normalized; cosine similarity via FAISS `IndexFlatIP`. Lock `EMBEDDING_DIM=512` / `SIMILARITY_METRIC="cosine"` in `domain/models.py`; every adapter must emit normalized vectors.
- **Detector and embedder stay in separate adapter modules** even though both ship in the `buffalo_l` bundle — sharing the import breaks NFR-1.
- **Enrollment is replace-not-append (FR-E3);** per-photo failures don't abort the request (FR-E4).

## FAISS lifecycle (the trickiest part — see architecture §7)

File-backed index per school in blob storage (`index.faiss` + `id_map.json` + `meta.json`). `meta.json.version` is the cache-invalidation key, bumped on every successful write and written **last** as the commit point. Each worker keeps an LRU cache of loaded indexes; the read path re-checks `meta.version` (cheap HEAD) and reloads on staleness. On read, validate `meta.embedding_model_version` matches the configured embedder and **fail loud** on mismatch — never search a stale-model index. v1 serializes writes via a single-replica enrollment deployment (Option A); per-school Redis lock (Option B) is the documented scale-up.

## Planned stack (architecture §6)

Python, hexagonal. FastAPI (CPU API pods) + GPU inference workers consuming Redis Streams. InsightFace (SCRFD detector + ArcFace embedder), faiss-cpu, decord for video frames, Azure Blob media store, Postgres via SQLAlchemy 2.x async (asyncpg), pydantic-settings for config. Observability: prometheus_client + structlog + OTel spans around port calls (never label metrics with `student_id` — cardinality bomb).

No build/test commands exist yet. When scaffolding, add them here.
