# 00 — Backend overview

The backend is the product's **core system**: it owns identity and PII (schools,
users, students, events, media metadata), orchestrates the ML service (enroll +
inference), and serves the distribution UX (galleries, downloads). It is the **only
caller** of the ML service; the ML service **never calls the backend**.

See [decisions/0022](../../../decisions/0022-backend-architecture-and-scope.md) for
the architecture decision and the owner-locked forks; this doc is the reference map.

## What it does (the flow)

1. **Platform** operators onboard a **school** (setting a `max_teachers` cap) and
   bootstrap its first **school admin**.
2. The **school admin** logs in and creates **teacher/staff** accounts, up to the cap.
3. Staff (admin + teachers) create a **student roster** and upload **one reference
   photo** per student → the backend uploads it to Supabase and calls the ML
   **enroll** API. Staff may provision a **student login** (email + temp password).
4. Staff create an **event**, then upload event **media** (images/videos) → each file
   goes to Supabase and the backend enqueues an ML **inference job**.
5. Users watch **job status** (a poller flips `queued`→`completed` when the ML worker
   has written the media's detection row).
6. Once processed, photos are browsable in **two views** — student→events→photos and
   event→students→photos — plus **browse-all** (all photos, or one student's).
   **Students** log in and see only the **photos/events they appear in**.

v1 is **view + download only** — no payments.

## Architecture: ports + adapters (mirrors the ML service)

The backend uses the **same ports-and-adapters structure as the ML service**: a
Protocol port per external system, a name→class registry, `BE_*_IMPL` config
selectors, and a lazy container that builds adapters from settings and injects them.
Services import only the ports — concrete libs (SQLAlchemy, httpx, redis, supabase)
live solely in `adapters/`. Selecting the `local_fs` object store + `inproc` job
producer runs the whole backend without Supabase or Redis (as the ML service already
allows), and provider portability (Supabase→S3) is a config swap. The DB stays
Postgres (Alembic migrations bind it); its repository ports exist for testability,
not RDBMS swapping. Conventions mirror ML: `pydantic-settings` (`BE_` prefix,
`SecretStr`), async SQLAlchemy 2.x + asyncpg, structlog JSON, `/healthz` +
dependency-probing `/readyz`, app-factory + `lifespan`.

```
services/backend/src/backend/
  settings.py            # full BE_ surface incl. *_impl selectors (object_store, job_producer, repository, ml_client)
  main.py                # create_app()+lifespan; builds the container onto app.state
  deps.py                # FastAPI Depends (session, current_user, require, scoped_school)
  domain/                # ports.py (Protocol per external system) + shared types/errors
  services/              # business logic (auth school user student event media gallery) — imports only domain
  adapters/              # one subpackage per port — the ONLY place SQLAlchemy/httpx/redis/supabase are imported
    repositories/        #   postgres_* (schools users students events media) + ml_results reader
    storage/             #   supabase_storage.py | local_fs_storage.py    (ObjectStore port)
    ml_client/           #   http_ml_client.py (httpx) | fake              (MlEnrollmentClient port)
    queue/               #   redis_job_producer.py | inproc_job_producer.py (JobProducer port)
  wiring/                # registry.py (name→class per port) + container.py (lazy build + inject)
  db/                    # base.py, models.py (backend ORM tables), session.py, ml_read.py (read-only ML tables), migrations/
  auth/                  # security.py (argon2+JWT), permissions.py (resolver seam), dependencies.py
  api/routers/           # health auth platform staff students events media galleries me
  observability/         # logging.py (structlog); metrics.py optional
  workers/               # job_status_poller.py (dedicated process)
```

**Layer rules:** routers do HTTP + authz only; services hold business logic and
transactions and import only `domain` ports; `adapters/` is the only place concrete
libs (SQLAlchemy, httpx, redis, supabase) are imported; `wiring/` builds adapters
from the `BE_*_IMPL` config and injects them. A CI layering grep (mirroring the ML
service's) keeps concrete libs out of `domain/` and `services/`. **All ML-schema
reads are isolated** to `db/ml_read.py` + the `ml_results` reader adapter — the
single coupling point.

## Data model (backend-owned; own Alembic chain)

Backend PKs are `uuid`; their **string form is the opaque ID sent to ML** — no
mapping table (`matches.school_id == str(schools.id)`). Fields tagged **[→ML]** are
handed to the ML service.

| Table | Key columns |
|---|---|
| `schools` | `id`**[→ML school_id]**, `name`, `max_teachers`, `status` |
| `users` | `id`, `school_id`→schools (null = platform_admin), `email` (unique), `password_hash`, `role`, `status` |
| `students` | `id`**[→ML student_id]**, `school_id`**[→ML]**, `user_id`→users (nullable), `full_name`, `reference_photo_path`**[→ML photo_uris]**, `enrollment_status`, `enrolled_at` |
| `events` | `id`**[→ML event_id]**, `school_id`**[→ML]**, `name`, `description`, `event_date`, `created_by`, `status` |
| `media` | `id`**[→ML media_id]**, `school_id`**[→ML]**, `event_id`→events**[→ML]**, `storage_path`**[→ML media_uri]**, `media_type`**[→ML]**, `processing_status`, `enqueued_at`, `completed_at`, `attempts`, `error` |

Full column detail (types, indexes, constraints) lands in `01-data-model.md` with
Phase 1's migration.

> **Critical:** the backend Alembic chain shares the `app` database with the ML
> chain, so `migrations/env.py` sets `version_table="alembic_version_backend"` — else
> the two histories corrupt each other's `alembic_version`. Backend tables must not
> collide with ML's names.

### ML tables the backend reads (owned by the ML service)

- `matches` — one row per `(media_id, student_id)`; the deduped "who is in this media"
  answer. Indexed `(school_id, event_id)` and `(school_id, student_id)`.
- `student_media_appearances` (view) — per-frame appearances (for in-photo boxes).
- `media_detections` — one row per processed media; **its presence = job done.**

## RBAC

Roles `platform_admin | school_admin | teacher | student`. A `Permission` enum +
hardcoded `ROLE_PERMISSIONS`, but all checks go through one
`PermissionResolver.permissions_for(user)` so per-school overrides can be added later
with no call-site change. Enforced by FastAPI deps: `get_current_user`,
`require(*perms)`, `scoped_school` (tenant match), `require_student`. Every repo read
is scoped by `school_id` (and `student_id` for students).

## API surface (prefix `/v1`)

- **Auth (public):** `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me`.
- **Platform:** `POST/GET /platform/schools`, `GET/PATCH /platform/schools/{sid}`,
  `POST /platform/schools/{sid}/admins`.
- **School admin:** `POST/GET/PATCH/DELETE /schools/{sid}/staff` (teacher cap enforced).
- **Students + enrollment:** `.../students` CRUD; `.../students/{stid}/reference-photo`
  (upload→enroll); `.../students/{stid}/enroll` (refresh) + `DELETE` (unenroll);
  `.../students/{stid}/account` (provision login).
- **Events + media + status:** `.../events` CRUD; `.../events/{eid}/media` (upload+enqueue);
  `.../events/{eid}/media`, `.../media/{mid}`, `.../events/{eid}/status`, `.../media/{mid}/reprocess`.
- **Galleries:** `.../events/{eid}/students`, `.../events/{eid}/students/{stid}/media`,
  `.../students/{stid}/events`, `.../students/{stid}/media`, browse-all
  `GET /schools/{sid}/media?event_id=&student_id=&status=`, `.../media/{mid}/appearances`.
- **Student (self-scoped):** `GET /me/events`, `/me/events/{eid}/media`, `/me/media`.
- **Download:** `GET .../media/{mid}/download` → short-lived Supabase signed URL, authz-gated.

## ML integration contract (binding — see decision 0022)

- **Enroll:** `POST {ML}/v1/schools/{sid}/students/{stid}/enroll` `{photo_uris:[path]|null}`; `DELETE` same path.
- **Enqueue:** `XADD` to `BE_QUEUE_STREAM` (== `ML_QUEUE_STREAM`, default `inference-jobs`) with exactly
  `media_id, media_uri, school_id, event_id, media_type` (all strings; `media_type ∈ {image,video}`).
- **Read results:** `matches` / `student_media_appearances` / `media_detections`, scoped by `school_id`.
  Job done = a `media_detections` row exists (requires `ML_PERSIST_DETECTIONS=true`). Failure = timeout sweep.
- **Storage:** upload to `BE_SUPABASE_BUCKET` (== `ML_SUPABASE_BUCKET`, default `media`); store the
  bucket-relative path; `reference-photos/…` vs `events/…` prefixes.

## Phase roadmap

| Phase | Decision | Delivers |
|---|---|---|
| 0 | 0022 | Architecture + scope (this doc) — no code |
| 1 | 0023 | Settings, DB, Alembic chain, `schools`+`users`, health |
| 2 | 0024 | JWT auth + RBAC |
| 3 | 0025 | Platform + school onboarding, teacher cap |
| 4 | 0026 | Students + ML enrollment |
| 5 | 0027 | Events + media upload + enqueue + job status |
| 6 | 0028 | Galleries (two views + browse-all) + download |
| 7 | 0029 | Hardening: obs, CORS, ML-schema contract test, compose/CI |
