# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working rules (always follow)

- **Record every decision.** Any change or non-trivial decision gets a dated entry in `decisions/` (see `decisions/README.md` for the format). Update the index there.
- **Keep this file current.** When architecture, commands, or conventions change, update CLAUDE.md in the same change.
- **Never commit or push on your own.** Make and verify changes, but do not run `git commit`, `git push`, or open PRs until the user explicitly asks. Leave changes staged/unstaged for them to review.
- **Self-review.** After making changes, review your own work and fix the issues you introduced before reporting done.
- **Review→fix loop (2×) after each phase.** After implementing a phase, run a *review agent → apply fixes* cycle **twice** — distinct focus per round (round 1: correctness / bugs / async / error-handling; round 2: edge cases / quality / simplification / test-coverage gaps) — verifying the gate (ruff + mypy + pytest + layering) is green after each round, **before** presenting the phase. Then stop for the user's review/approval before starting the next phase.
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

The structure above is **scaffolded** (see [decisions/0004](decisions/0004-scaffold-monorepo.md)): each service is a runnable shell with `/healthz` + `/readyz` and a passing health test. The ML service additionally has its implemented `domain/` + `orchestration/` core (Phase 1, [decisions/0008](decisions/0008-domain-core-design.md)); the **backend build-out is underway** — architecture + scope locked in [decisions/0022](decisions/0022-backend-architecture-and-scope.md) (ports + adapters like the ML service, roll-our-own JWT, reads ML results from the shared DB; docs-first phases, reference in `services/backend/docs/`). **Phase 1 (foundations) has landed** ([decisions/0023](decisions/0023-backend-db-schema.md)): settings, the backend DB + its **own** Alembic chain (`schools`/`users`, migration `0001`, distinct version table `alembic_version_backend`), the ports/registry/container skeleton, structlog, and dep-probing `/readyz`. **Phase 2 (auth + RBAC) has landed** ([decisions/0024](decisions/0024-auth-jwt-and-rbac.md)): roll-our-own JWT (argon2 `PasswordHasher` + PyJWT `TokenService` ports, services stay crypto-free), the `Permission`/`ROLE_PERMISSIONS` RBAC behind one `PermissionResolver` seam, `get_current_user`/`require_permissions` deps, `/v1/auth/{login,refresh,change-password,me}`, migration `0002` (`users.must_change_password`) + case-insensitive email, and the platform-admin bootstrap CLI. Phases `0025`–`0029` follow. FE remains a shell.

> The TEMP wiring demo (decisions/0006) has been **removed** in Phase 4
> ([decisions/0017](decisions/0017-docker-observability-ci.md)): the `demo.py`
> modules, `/temp/*` routes, `demo_events` table, FE `app/temp/` + `app/api/temp/`,
> and the TEMP deps/env are gone. FE/BE are clean shells again until real features
> land; the ML service now runs its real enrollment API + inference worker.

## Commands

Run Python commands from the repo root (uv workspace). `uv` fetches Python 3.12 itself.

```bash
uv sync --all-packages              # install all workspace deps (creates .venv)
uv run pytest                       # all Python tests
uv run pytest services/ml_service   # a single service's tests
uv run ruff check . && uv run mypy .
./scripts/check.ps1                 # local gate: ruff + mypy + layering grep + pytest
uv run uvicorn ml_service.api.main:app --reload          # ML API       :8000 (/metrics too)
uv run python -m ml_service.workers.inference_worker      # ML inference worker
uv run uvicorn backend.main:app --reload --port 8001     # backend     :8001
# Apply ML DB migrations (URL from env, never committed):
ML_DATABASE_URL=postgresql+asyncpg://... uv run alembic -c services/ml_service/alembic.ini upgrade head
# Apply backend DB migrations (separate chain, version table alembic_version_backend):
BE_DATABASE_URL=postgresql+asyncpg://... uv run alembic -c services/backend/alembic.ini upgrade head
# Bootstrap the first platform admin (args/getpass, never .env; needs a migrated DB):
BE_DATABASE_URL=postgresql+asyncpg://... uv run python -m backend.cli.bootstrap_admin --email ops@example.com
cd frontend && npm install && npm run dev                # frontend    :3000
docker compose up --build           # all 3 images + Postgres + Redis (needs Docker running)
./scripts/up.ps1                    # helper: Postgres+Redis detached (stay up), apps in foreground; Ctrl+C stops only the apps
```

Helper scripts live in `scripts/` (see `scripts/README.md`).

Notes for future instances:
- The Python Dockerfiles build from the **repo root** context (they need root `pyproject.toml` + `uv.lock`); only the frontend builds from `./frontend`.
- pytest uses `--import-mode=importlib` so same-named test files coexist across services — don't add `__init__.py` to `tests/` dirs.
- New Python deps go in the **service's** `pyproject.toml`; shared dev tools in the root `[dependency-groups] dev`. Re-run `uv sync --all-packages` after.

## Status: Phase 4 done (Docker + observability + CI + TEMP removal) — v1 feature-complete

The repo is git-initialized (`main`) with a secrets-safe `.gitignore`. The ML service is being built in reviewed phases. **Phase 1** delivered the pure `domain/` (models, the 9 ports, `apply_threshold_and_gap`, errors) + `orchestration/` (`EnrollmentService`, `InferenceService`). **Phase 2** delivered a real adapter for every port under `adapters/` — `SCRFDDetector` + `ArcFaceEmbedder` (InsightFace `buffalo_l`, separate modules), `FaissPerSchoolVectorIndex` (+ pluggable index store, LRU cache), `SupabaseMediaStore`/`LocalFsMediaStore`, `DecordFrameExtractor`/`OpenCvFrameExtractor`, `PostgresMatchRepository`/`PostgresThresholdProvider`/`PostgresReferencePhotoRepository`, and `RedisStreamsJobQueue`/`InProcJobQueue` — plus the ML metadata schema in `db/` with Alembic (`0001_initial`). **Phase 3 is complete** (see [decisions/0016](decisions/0016-wiring-api-worker.md)): the wiring composition root (`wiring/settings.py` full req §12 surface, `wiring/registry.py` name→class per port, `wiring/container.py` lazy-memoized adapter build + inject), the enrollment API (`api/routes/enrollment.py` `POST …/enroll` + `DELETE …`, `api/deps.py` container-backed, `api/routes/health.py` with dep-probing `/readyz`, central error mapping in `api/main.py`), and the inference worker (`workers/runner.py` consume/ack/nack + retry/DLQ, `workers/inference_worker.py` entrypoint). **Phase 4 is complete** (see [decisions/0017](decisions/0017-docker-observability-ci.md)): the Dockerfile builds one image runnable as API/worker/migrate with `buffalo_l` baked in at build time; `docker-compose.yml` adds an `ml-worker` service + a shared `faiss` volume (API writes / worker reads); `observability/{metrics,logging,tracing}.py` provide the req §13 Prometheus metrics (served at `GET /metrics`), structlog JSON logging, and opt-in OTel tracing (via `ML_OTEL_EXPORTER_OTLP_ENDPOINT`); CI (`.github/workflows/ci.yml`) + `scripts/check.ps1` run ruff/mypy/pytest + the layering grep, plus a `docker-build` job; and the TEMP wiring demo is fully removed. 106 tests pass (+5 gated on real Postgres/Redis/models); ruff/mypy/layering clean. Design docs with diagrams live in `services/ml_service/docs/` (`00`–`09`). **Not yet run on this host:** the Docker build + `buffalo_l` bake and the InsightFace runtime path (they execute in CI's `docker-build` job / on a Docker host). **Post-v1:** the inference worker now persists the full per-face **detection audit** — media-centric `media_detections`/`media_frames`/`face_detections`/`face_detection_candidates` (replace-by-media) + `matches.frames_matched` + the `student_media_appearances` view — via a 10th `DetectionRepository` port and Alembic `0002`; see [decisions/0021](decisions/0021-persist-per-frame-detections.md). The two ML-service specs remain the binding source of truth:

- `ml-service-requirements.md` — locked v1 requirements (the "what"). Source of truth for functional/non-functional requirements, locked decisions (§8), interface contracts (§9), and data contracts (§10).
- `ml-service-architecture.md` — v1 architecture (the "how"). Source of truth for module layout (§5), adapter choices + versions (§6), and the FAISS index lifecycle (§7).

When implementing, treat both docs as binding. The architecture doc's §5 module tree is the intended layout (relocated under `services/ml_service/src/ml_service/`); §6's adapter table fixes the initial library choices and versions. If a code change contradicts either doc, surface the conflict rather than silently diverging.

## What this service is

A multi-tenant face-recognition service for distributing event photos/videos to the students who appear in them. Two pipelines that share one embedding model version but are otherwise independent:

- **Enrollment** (synchronous HTTP, student-id-triggered): resolve a student's reference-photo URIs → fetch → detect → embed → upsert into a per-school vector index (see [decisions/0009](decisions/0009-enrollment-contract.md)).
- **Inference** (async, queue-driven workers): fetch media → (video) extract frames at fixed FPS → detect → embed → search the school's index → apply threshold/gap decision → dedupe → persist match records.

## Architecture: hexagonal (ports and adapters)

The design exists to satisfy NFR-1/NFR-2 (swap ML stack or storage by config alone). The whole structure depends on strict layering:

- `domain/` — pure, imports no third-party libs. Models, the 10 `Protocol` ports (req §9 + `ReferencePhotoRepository` (see [decisions/0009](decisions/0009-enrollment-contract.md)) + `DetectionRepository` (see [decisions/0021](decisions/0021-persist-per-frame-detections.md))), and the pure `apply_threshold_and_gap()` decision function.
- `orchestration/` — `EnrollmentService` / `InferenceService`, plus the shared `identify_in_frames` kernel (`identify.py` — the per-frame `face → person` loop used by both the worker and the dev test UI, [decisions/0020](decisions/0020-identify-all-faces-and-per-frame.md)); `InferenceService` also maps that timeline into the detection audit written via `DetectionRepository` ([decisions/0021](decisions/0021-persist-per-frame-detections.md)). Imports only `domain`.
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
- **Two-layer idempotency (NFR-5):** in-memory worker dedupe keyed on `(student_id, media_id)` first; DB unique constraint on `(media_id, student_id)` as the second line of defence. `save_batch` is the only **`matches`** write path and uses `INSERT ... ON CONFLICT` where higher confidence wins. (The detection audit is a separate, independently-idempotent write path — replace-by-media — [decisions/0021](decisions/0021-persist-per-frame-detections.md).)
- **Decision logic (req §6.2):** top-K=2. ≥threshold filter; 0 → unknown (log only, no record, FR-I8); 1 → emit; 2 → emit top-1 alone if `(top1-top2) > gap`, else emit both with `needs_review=true`.
- **Identification is per-face (`face → person`), across every frame.** `identify_in_frames` (`orchestration/identify.py`) detects **every** face in **every** frame and decides each independently — a group photo names everyone; one frame can match several students. The worker persists the deduped best per `(student_id, media_id)` as `matches` (the two-layer idempotency above), but the kernel *also* returns the full per-frame/per-face timeline (`frames[]`, incl. each face's raw top-k candidates) — the dev test UI renders it for video (per timestamp, **not** globally deduped), and the worker **persists** it as a media-centric detection audit (`media_detections`/`media_frames`/`face_detections`/`face_detection_candidates`, replace-by-media) plus `matches.frames_matched` and the `student_media_appearances` view — see [decisions/0021](decisions/0021-persist-per-frame-detections.md).
- **Embedding convention:** 512-dim ArcFace, L2-normalized; cosine similarity via FAISS `IndexFlatIP`. Lock `EMBEDDING_DIM=512` / `SIMILARITY_METRIC="cosine"` in `domain/models.py`; every adapter must emit normalized vectors.
- **Detector and embedder stay in separate adapter modules** even though both ship in the `buffalo_l` bundle — sharing the import breaks NFR-1.
- **Enrollment is replace-not-append (FR-E3);** per-photo failures don't abort the request (FR-E4).

## FAISS lifecycle (the trickiest part — see architecture §7)

File-backed index per school in blob storage (`index.faiss` + `id_map.json` + `meta.json`). `meta.json.version` is the cache-invalidation key, bumped on every successful write and written **last** as the commit point. Each worker keeps an LRU cache of loaded indexes; the read path re-checks `meta.version` (cheap HEAD) and reloads on staleness. On read, validate `meta.embedding_model_version` matches the configured embedder and **fail loud** on mismatch — never search a stale-model index. v1 serializes writes via a single-replica enrollment deployment (Option A); per-school Redis lock (Option B) is the documented scale-up.

## Planned stack (architecture §6)

Python, hexagonal. FastAPI (CPU API pods) + GPU inference workers consuming Redis Streams. InsightFace (SCRFD detector + ArcFace embedder), faiss-cpu, **Supabase Storage** media store (default; `local_fs` for dev — diverges from architecture §6's Azure default, see [decisions/0010](decisions/0010-supabase-media-store.md)), decord for video frames (OpenCV fallback), Postgres via SQLAlchemy 2.x async (asyncpg), pydantic-settings for config. Observability: prometheus_client (`/metrics`, req §13 counters + latency histogram) + structlog (JSON) + opt-in OTel tracing at the service-call boundary — labels are `school_id` + model versions only, never `student_id`/`media_id` (cardinality bomb). See [decisions/0017](decisions/0017-docker-observability-ci.md) + docs/09.

**Platform note:** `insightface` and `decord` have no Windows/py312 wheels, so they are declared Linux-only (`; sys_platform == 'linux'`) — they run in the Docker image; local Windows dev uses the OpenCV extractor and import-gated tests. All other heavy deps install cross-platform. See [decisions/0014](decisions/0014-queue-and-platform-adapters.md).
