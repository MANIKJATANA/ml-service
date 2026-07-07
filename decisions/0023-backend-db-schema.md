# 0023 — Backend DB schema (Phase 1: foundations + `schools`/`users`)

**Date:** 2026-07-08
**Status:** Accepted

## Context

Phase 1 of the backend build-out ([0022](0022-backend-architecture-and-scope.md))
stands up the foundations: settings, the DB layer + the backend's **own** Alembic
chain, the ports/wiring skeleton, observability, and health — plus the first two
identity tables, `schools` and `users`. The remaining tables (`students`, `events`,
`media`) land with their phases (`0026`/`0027`), each as a chained migration.

## Decisions

### Own Alembic chain in the shared DB — distinct version table

The backend targets the **same** `app` Postgres as the ML service but owns a separate
Alembic history under `services/backend/src/backend/db/migrations`. Its `env.py`
reads `BE_DATABASE_URL` (asyncpg) and sets **`version_table="alembic_version_backend"`**
(both offline and online) so the two chains never touch each other's bookkeeping. A
one-shot `backend-migrate` compose service runs `alembic upgrade head` before the API
starts (mirroring the ML `migrate` service). `alembic.ini` uses `%(here)s` paths and
stores **no** DSN. `compare_type=True`, hand-authored migrations (working rule 0007).

### `schools`

| column | type | notes |
|---|---|---|
| `id` | uuid PK (`uuid4`) | **[→ML `school_id`]** — its string form is the opaque tenant id |
| `name` | text not null | |
| `max_teachers` | int not null | staff cap enforced in Phase 3 |
| `status` | text not null, default `'active'` | CHECK ∈ {active, suspended} |
| `created_at` / `updated_at` | timestamptz not null, `now()` | `updated_at` bumped on ORM update |

### `users`

| column | type | notes |
|---|---|---|
| `id` | uuid PK (`uuid4`) | account id (JWT `sub`) |
| `school_id` | uuid FK→`schools.id` **nullable**, `ON DELETE CASCADE` | **null ⇔ `platform_admin`** |
| `email` | text not null | **`unique`** (global, one account per email) |
| `password_hash` | text not null | argon2 (set in Phase 2; column exists now) |
| `role` | text not null | CHECK ∈ {platform_admin, school_admin, teacher, student} |
| `status` | text not null, default `'active'` | CHECK ∈ {active, disabled} |
| `created_at` / `updated_at` | timestamptz not null, `now()` | |

Constraints/indexes: `uq_users_email` (unique email); `ix_users_school_role`
(`school_id`, `role`); **`ck_users_school_role`** — `(role='platform_admin' AND
school_id IS NULL) OR (role<>'platform_admin' AND school_id IS NOT NULL)`, enforcing
the tenant rule at the DB. A CASCADE from `schools` keeps deletes clean in dev.

### ID convention: UUID in the DB, `str` in the domain

ORM PKs are `UUID(as_uuid=True)` (Postgres `uuid`, `default=uuid4`). Domain models
(`domain/models.py`, frozen slotted dataclasses) carry **`str` ids** — repositories
convert `UUID → str` on read. The string form is exactly what the ML service receives
(`str(school.id) == matches.school_id`), so no conversion is needed at the ML
boundary and web edges (path params, JWT claims, JSON) are naturally strings.

### Ports + adapters for the repositories

`domain/ports.py` defines `SchoolRepository` and `UserRepository` Protocols (minimal
methods needed by Phases 2–3: create / get / get_by_email / list). `adapters/
repositories/postgres_{schools,users}.py` implement them over an
`async_sessionmaker`. `wiring/registry.py` maps `repository_impl="postgres"` → those
classes; `wiring/container.py` builds the engine/sessionmaker once and memoizes each
repo, and exposes `check_readiness()` (a bounded `SELECT 1`) for `/readyz` + `aclose()`.
Services (later phases) depend only on the ports; concrete SQLAlchemy lives solely in
`adapters/`. A backend `tests/test_layering.py` (AST, mirroring the ML one) keeps
`domain/`+`services/` free of `sqlalchemy`/`fastapi`/`httpx`/`redis`/`supabase`.

### Settings grow per phase

`settings.py` gains the Phase-1 surface: `service_name`, `log_level`, `log_json`,
`database_url`, `db_echo`, `ml_service_url` (kept), `repository_impl`,
`readiness_timeout_s`. The object-store / job-producer / ML-client selectors + their
config (Supabase, Redis, JWT secret, poll/timeout) arrive with the phases that build
those adapters — settings track the code that uses them.

### Dependencies added (Phase 1)

`sqlalchemy[asyncio]>=2.0`, `asyncpg`, `alembic` (runtime — the image runs
`alembic upgrade head`), `structlog`. All are already in `uv.lock` via the ML
service, so this only adds `backend` as a dependent. Others (`passlib`, `pyjwt`,
`redis`, `httpx`, `supabase`, `email-validator`) come with their phases.

## Consequences

- `docker compose up` runs `backend-migrate` (backend chain) alongside `migrate` (ML
  chain) against one DB, each with its own `alembic_version*` table.
- The full architecture is proven end-to-end for the two identity tables
  (ORM → migration → port → adapter → registry → container → readiness), de-risking
  the pattern before Phases 2+ build on it.
- Backend dev runs natively on Windows (no Linux-only wheels); DB-backed repository
  tests are gated on `BE_TEST_DATABASE_URL` (like the ML service's gated PG tests),
  so the default gate stays green without a live Postgres.

## Alternatives considered

- **One table per phase, users in Phase 2** — reasonable, but `schools`+`users` are
  the tenant/identity core and pair naturally; creating both now lets Phase 2 focus
  purely on auth logic rather than schema.
- **Shared `alembic_version`** — rejected (corrupts cross-chain bookkeeping); the
  distinct `version_table` is mandatory, per [0022](0022-backend-architecture-and-scope.md).
- **`CITEXT` for case-insensitive email** — deferred; v1 stores email as-entered with
  a plain unique index. Normalisation (lowercasing on write) is handled in the service
  layer in Phase 2 and can become a `CITEXT`/functional index later if needed.
