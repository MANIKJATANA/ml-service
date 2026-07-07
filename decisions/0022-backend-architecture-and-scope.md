# 0022 — Backend architecture & scope (build-out begins)

**Date:** 2026-07-07
**Status:** Accepted

## Context

The ML service is v1-complete. The **backend** (`services/backend/`) — the "core
system" the requirements defer all upload/storage/distribution UX to (req §1,
[0003](0003-monorepo-structure.md)) — is still a bare FastAPI shell (health probes
only: no DB, no auth, no routes). This decision opens the backend build-out: it
locks the **architecture, scope, and the cross-cutting integration rules** that all
subsequent backend phases build on. Per-area detail (schema, auth, onboarding,
enrollment, media/status, galleries, hardening) lands in its own decision record
(`0023`–`0029`) as each phase is implemented.

The product: platform operators onboard **schools**; a **school admin** creates
**staff** (capped) and **students**; staff create **events** and upload event media
to Supabase; the backend enqueues an ML inference job per media; users watch job
**status**; once processed, photos are shown in **two views** (student→events→photos
and event→students→photos) plus **browse-all**, with **students seeing only the
photos/events they appear in**.

The [0003](0003-monorepo-structure.md) open item — "BE framework details beyond
FastAPI (DB, auth) — defer until BE work starts" — is now resolved here.

## Owner-locked decisions (the forks that shape everything)

1. **Auth = roll-our-own JWT.** The backend owns email+password (argon2 via
   passlib), issues/verifies its own access+refresh JWTs. Identity lives fully in
   the backend DB. No Supabase Auth. (Detail in `0024`.)
2. **ML results = read the shared Postgres directly.** The ML service writes
   `matches` + the `student_media_appearances` view + `media_detections` to the
   **same** Postgres the backend uses, and **never calls the backend**. The backend
   reads those ML-owned tables/views directly, scoped by `school_id`. **Job
   completion is inferred from the presence of a `media_detections` row** for the
   `media_id` — there is no status callback. No ML-service changes. (Detail in
   `0027`/`0028`.)
3. **v1 = view + download only.** No payments/cart/checkout.
4. **Enrollment = staff-managed, one reference photo.** Admin/teacher creates each
   student and uploads **one** reference photo; the backend triggers ML enrollment.
   Students log in only to view. (Detail in `0026`.)
5. **Student login = staff sets a temp password** (changed on first login). No
   email/SMTP infra in v1.

## Decisions

### Ports + adapters, mirroring the ML service (per owner review)

The backend uses the **same ports-and-adapters structure as the ML service** — a
Protocol port per external system + a name→class registry + `BE_*_IMPL` config
selectors + a lazy-memoized container that builds adapters from settings and injects
them. Services depend only on the ports (no concrete IO-lib imports), so the same
layering invariant the ML service enforces applies here too.

Ports (each with ≥1 adapter): the **repositories** (schools/users/students/events/
media — DB), the **ML results reader** (the shared-DB read side), the **object
store** (`supabase` default, `local_fs` for credential-free dev — matching the ML
media store), the **ML enrollment client** (`http` via httpx; a fake for tests), and
the **job producer** (`redis` default, `inproc` for dev/test). Selecting `local_fs`
+ `inproc` lets the whole backend run locally without Supabase or Redis, exactly as
the ML service already does — and portability (e.g. Supabase→S3) is a config swap.

The **DB stays Postgres** — Alembic migrations are Postgres-specific, so the
repository ports exist for testability and consistency (fake vs Postgres adapter),
not to swap the RDBMS. Conventions still mirror ML: `pydantic-settings` `BE_` prefix
+ `SecretStr`; async SQLAlchemy 2.x + asyncpg + `async_sessionmaker`; structlog JSON;
`/healthz` + dependency-probing `/readyz`; app-factory + `lifespan` building the
container onto `app.state`.

Layout: `domain/` (ports + shared types/errors), `services/` (business logic, imports
only `domain`), `adapters/` (one subpackage per port — the only place SQLAlchemy/
httpx/redis/supabase are imported), `wiring/` (settings/registry/container),
`api/routers/`, `db/` (ORM + migrations + session + `ml_read.py`), `auth/`,
`workers/`. Each phase introduces the ports + adapters it needs; a CI layering grep
(mirroring the ML service's) keeps concrete libs out of `domain/` and `services/`.

### The backend owns all identity/PII; IDs map by string

Consistent with [0012](0012-db-schema-and-alembic.md) (identity stays in the
backend), the backend owns `schools`, `users`, `students`, `events`, and event
`media`. Backend PKs are `uuid`; their **string form is the opaque ID handed to the
ML service** (`matches.school_id == str(schools.id)`, etc.) — no mapping table.
Invariant: canonical lowercase-hyphenated UUID strings, so backend↔ML string joins
line up.

### Two Alembic chains, one shared database (critical)

Both the backend and ML target the **same** `app` Postgres. The backend gets its
**own** Alembic chain; its `env.py` reads `BE_DATABASE_URL` and **must** set a
distinct bookkeeping table — `version_table="alembic_version_backend"` — or the two
histories corrupt each other's `alembic_version`. Backend table names must not
collide with ML's (`matches`, `school_thresholds`, `student_reference_photos`,
`media_detections` + children).

### ML-schema reads are isolated to one module

All reads of ML-owned tables live in `db/ml_read.py` (read-only SQLAlchemy Core
`Table()` definitions — **not** registered in the backend `Base.metadata`, so backend
Alembic never manages them) plus `repositories/ml_results.py`. This is the single
coupling point to the ML schema. A Phase-7 `information_schema` **contract test**
asserts the consumed columns still exist, so an ML migration that drops/renames one
fails backend CI loudly rather than at runtime.

### RBAC is static now, extensible later

Roles: `platform_admin` (null `school_id`), `school_admin`, `teacher`, `student`.
A `Permission` enum + hardcoded `ROLE_PERMISSIONS`, but **every check routes through
one `PermissionResolver.permissions_for(user)`**. v1 ships `StaticPermissionResolver`;
a later `DbPermissionResolver` overlays per-school override rows with **zero
call-site change** — satisfying the owner's "define at our level now, hand the choice
to school admins later." Tenant isolation is enforced **at the query layer**: every
repo read takes `school_id` (and `student_id` for students) as an explicit argument.
(Detail in `0024`.)

### "Precompute student→events" is a live query, not a table

The owner's instinct to precompute which events a student appears in is already
served by ML's existing `(school_id, student_id)` index on `matches`
(`SELECT DISTINCT event_id FROM matches WHERE school_id=? AND student_id=?`). A
precompute *during detection* is **not available** to us — it would require the ML
service to know backend concepts and violate "no ML changes / ML never calls BE."
Any materialization must be **backend-side**, maintained in the completion poller,
and is deferred until profiling on real data justifies it.

### Phased, docs-first rollout

Each phase locks a decision record, then lands code + tests:
`0022` architecture/scope (this) · `0023` DB schema · `0024` auth+RBAC · `0025`
onboarding+teacher-limits · `0026` enrollment integration · `0027` media+job-status
· `0028` galleries+reads · `0029` hardening. Ordering: auth precedes protected
routes; enrollment precedes results (a student must be enrolled to be matched);
galleries last (depend on populated ML tables).

### Dependencies to add (`services/backend/pyproject.toml`)

`sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic` (runtime — the image runs
`alembic upgrade head`), `redis>=5`, `httpx>=0.27`, `passlib[argon2]`, `pyjwt>=2.9`,
`python-multipart`, `supabase`, `structlog`, `email-validator`. All install
cross-platform — unlike the ML service, backend dev works natively on Windows (no
Linux-only wheels).

### Baked defaults (reasonable; revisit on request)

Global email uniqueness; `max_teachers` caps teacher accounts only; UI maps
`queued`→"processing" (no observable processing state); first `platform_admin`
bootstrapped via a management command (args, never `.env`); RBAC override tables
deferred; media proxied through the backend in v1 (signed direct-to-Supabase is a
scale follow-up); download via short-lived Supabase signed URLs; one shared value
feeds each of `{ML,BE}_QUEUE_STREAM` and `{ML,BE}_SUPABASE_BUCKET`; backend
`/metrics` optional (Phase 7).

## Integration contract (verified against ML code — binding)

- **Enroll:** `POST {ML}/v1/schools/{school_id}/students/{student_id}/enroll` body
  `{photo_uris:[...] | null}`; `DELETE {ML}/v1/schools/{school_id}/students/{student_id}`
  (`api/routes/enrollment.py`).
- **Enqueue:** Redis `XADD` to `queue_stream` (`ML_QUEUE_STREAM`, default
  `inference-jobs`) with **exactly** the five string fields `_encode` produces —
  `media_id, media_uri, school_id, event_id, media_type` (`media_type ∈
  {"image","video"}`). A missing field makes the ML worker dead-letter the job as
  malformed (`adapters/queue/redis_streams.py`). `BE_QUEUE_STREAM` must equal
  `ML_QUEUE_STREAM`.
- **Read results:** `matches` (indexed `(school_id,event_id)` and
  `(school_id,student_id)`), the `student_media_appearances` view, and
  `media_detections` (unique `media_id`, written on every processed media when
  `ML_PERSIST_DETECTIONS=true` — a hard operational invariant for completion
  detection). Never use `matches` row count as the completion signal (a zero-student
  photo still writes a `media_detections` row).
- **Storage:** upload to the same bucket ML reads (`supabase_bucket`,
  `ML_SUPABASE_BUCKET`, default `media`) and store the bucket-relative path as
  `media_uri` / `reference_photo_path`; distinct prefixes for `reference-photos/…`
  vs `events/…` (`adapters/media_store/supabase_storage.py`).

## Consequences

- The backend gains a concrete, reviewable architecture and a phase roadmap; the
  reference lives in `services/backend/docs/` and the per-phase rationale in
  `decisions/0023`–`0029`.
- The ML service is **not touched** — the backend integrates as its only caller
  (HTTP enroll + Redis producer) and reads results from the shared DB.
- Two known couplings are made explicit and guarded: the enqueue field/stream
  contract (producer-contract test, Phase 5) and the ML read-schema
  (`information_schema` contract test, Phase 7).
- Nothing runs yet — this phase is docs only. Phase 1 stands up settings, the DB,
  the Alembic chain (with the distinct version table), and health.

## Alternatives rejected

- **Plain layered backend (concrete impls, no config swap)** — initially proposed,
  then rejected on owner review in favour of full ports + adapters: consistency with
  the ML service, the real dev-value of `local_fs`/`inproc` adapters (run without
  Supabase/Redis), and provider portability (Supabase→S3 by config). The DB is the
  one exception — Postgres-concrete behind repository interfaces (migrations bind it).
- **Supabase Auth** — rejected by the owner in favour of self-issued JWTs (identity
  fully owned, no external auth dependency).
- **An ML read-API for results** (GET endpoints on the ML service) — rejected for
  v1: the shared-DB read is lighter, spec-sanctioned (req §10.1 indexes `matches`
  on `(school_id,event_id)` "for fan-out queries by core system"), and touches no
  ML code. The coupling is contained to `db/ml_read.py` and CI-guarded.
- **Copying ML results into backend tables via a sync** — rejected for v1: adds a
  write path and drift risk for no benefit at this scale; reconsider only if
  profiling demands it.
