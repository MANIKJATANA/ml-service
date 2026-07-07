# Decision Log

Every change and decision made in this repo gets recorded here as a dated entry, so the reasoning behind the code is never lost.

## How to use

- One file per decision: `NNNN-short-slug.md` (zero-padded sequence, e.g. `0001-use-faiss-per-school.md`).
- Keep entries short: context, the decision, and why. Note alternatives rejected when relevant.
- Add a one-line pointer to the index below.
- When a decision is superseded, don't delete it — add a new entry and mark the old one `Superseded by NNNN`.

## Index

- [0001 — Adopt decision log and working rules](0001-adopt-decision-log-and-working-rules.md) — how decisions are recorded and the repo's working conventions.
- [0002 — Initialize git repository](0002-initialize-git-repo.md) — `git init` on `main`, secrets-safe `.gitignore`, initial commit.
- [0003 — Monorepo structure: FE + BE + ML service, 3 images](0003-monorepo-structure.md) — Next.js + FastAPI BE + ML service; uv workspace; `services/` + `frontend/` layout.
- [0004 — Scaffold the monorepo (uv workspace + 3 images)](0004-scaffold-monorepo.md) — runnable shells, health endpoints, Dockerfiles, compose with Postgres + Redis.
- [0005 — Add scripts/ folder with a stack-up helper](0005-add-scripts-folder.md) — `scripts/up.ps1` wraps `docker compose up --build`.
- [0006 — Temporary end-to-end wiring demo](0006-temporary-wiring-demo.md) — **TEMP** FE→BE→ML (HTTP + Redis) with Postgres writes from both; to be removed.
- [0007 — All DB schema changes go through migrations](0007-db-migrations-in-migration-folder.md) — schema changes live in versioned migration files, never ad-hoc in application code.
- [0008 — Domain core design (Phase 1)](0008-domain-core-design.md) — pure frozen-dataclass models, async Protocol ports, the §9 signature divergences, and the no-fakes testing approach.
- [0009 — Enrollment contract & the ReferencePhotoRepository port](0009-enrollment-contract.md) — student-id-triggered enroll/refresh; ML resolves photo URIs from its own table and fetches via `MediaStore`; adds a 9th port.
- [0010 — Supabase Storage as the default MediaStore](0010-supabase-media-store.md) — Supabase Storage for media (event media + reference photos); diverges from architecture §6 (Azure); `local_fs` for dev.
- [0011 — FAISS per-school adapter lifecycle](0011-faiss-adapter-lifecycle.md) — `IndexFlatIP` per school, Option A in-process lock, pluggable index store (meta.json last), rebuild-on-write, over-fetch+collapse, fail-loud version check.
- [0012 — ML metadata schema + Alembic (async) migrations](0012-db-schema-and-alembic.md) — `matches`/`school_thresholds`/`student_reference_photos`; ML owns its schema; async Alembic reading `ML_DATABASE_URL`.
- [0013 — Carry detector landmarks inside FaceBox](0013-facebox-landmarks.md) — optional `FaceBox.landmarks` enables ArcFace `norm_crop` alignment without changing the `embed` port signature.
- [0014 — Redis Streams queue + in-proc queue; Linux-only heavy deps](0014-queue-and-platform-adapters.md) — default Redis Streams `JobQueue` (+ real in-proc), OpenCV video fallback, `insightface`/`decord` gated to Linux wheels.
- [0015 — Run DB migrations before the apps start](0015-run-migrations-before-apps.md) — one-shot `migrate` compose service (`alembic upgrade head`) gates the apps; `up.ps1` runs it between infra and apps.
- [0016 — Phase 3: wiring + API + worker](0016-wiring-api-worker.md) — settings/registry/container composition root; enrollment routes + central error mapping; the inference worker consume/ack/nack loop.
- [0017 — Phase 4: Docker, observability, CI, TEMP-demo removal](0017-docker-observability-ci.md) — one image/three roles + baked `buffalo_l`; `ml-worker` + shared FAISS volume; §13 metrics/structlog/OTel + `/metrics`; CI layering gate; TEMP demo removed.
- [0018 — Redis socket_timeout must exceed the XREADGROUP BLOCK window](0018-redis-socket-timeout-vs-block.md) — redis-py 8.x's 5s default `socket_timeout` collided with the queue's 5s `block_ms`, crashing the worker on idle polls; set `ML_REDIS_SOCKET_TIMEOUT_S=30`.
- [0019 — Dev-only browser test UI for enroll + identify](0019-dev-test-ui.md) — flag-gated `GET /test` page + `/v1/test/{enroll,check}` reusing the real container; adds a media-store `upload` helper; `ML_ENABLE_TEST_UI`. *(identify amended by 0020.)*
- [0020 — Identify every face (face → person); per-frame detail via a shared kernel](0020-identify-all-faces-and-per-frame.md) — `orchestration/identify.py` returns per-frame/per-face detail + a deduped people map; worker persistence unchanged; test UI names every face and reports video per timestamp; per-frame persistence designed-for (**implemented by [0021]**).
- [0021 — Persist the full per-face detection audit + a student view](0021-persist-per-frame-detections.md) — media-centric `media_detections`→`media_frames`→`face_detections`→`face_detection_candidates` (replace-by-media) + `matches.frames_matched` + the `student_media_appearances` view; adds the 10th `DetectionRepository` port; the kernel retains raw candidates; embeddings declined.
- [0022 — Backend architecture & scope (build-out begins)](0022-backend-architecture-and-scope.md) — ports + adapters like the ML service (registry + `BE_*_IMPL` selectors, `local_fs`/`inproc` dev adapters); roll-our-own JWT; backend reads ML results from the shared DB (job done = `media_detections` present, no ML changes); backend owns identity/PII (UUID-PK→opaque-ID string); two Alembic chains in one DB need distinct version tables; RBAC resolver seam (static now, per-school later); phased `0023`–`0029`.
- [0023 — Backend DB schema (Phase 1: foundations + schools/users)](0023-backend-db-schema.md) — own Alembic chain with a distinct version table (`alembic_version_backend`); `schools` (+ `max_teachers`) and `users` (nullable `school_id` = platform admin; role/tenant CHECKs); UUID PK in the DB, `str` id in the domain; `SchoolRepository`/`UserRepository` ports + Postgres adapters wired via registry/container.
