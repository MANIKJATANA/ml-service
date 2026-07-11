# 0029 — Hardening: HTTP metrics, CORS, the `matches` contract test, CI/compose parity (Phase 7)

**Date:** 2026-07-11
**Status:** Accepted

## Context

Phases 1–6 built the backend's whole feature surface: onboarding, auth/RBAC,
students + ML enrollment, events + media + event-level processing, and the
distribution galleries + download. The service *works*, but three production-shaped
gaps remain, all foreseen when the backend build-out was scoped as ending in a
hardening phase ([0022](0022-backend-architecture-and-scope.md), phase `0029`):

1. **No metrics.** The ML service exposes Prometheus at `GET /metrics`
   ([0017](0017-docker-observability-ci.md)); the backend exposes nothing, so there is
   no request-rate / latency / error signal for the API pods.
2. **No CORS.** The Next.js frontend (`:3000`) calls the backend (`:8001`)
   cross-origin. Browsers block that by default — the backend must opt specific
   origins in.
3. **An unguarded cross-service coupling.** Phase 6's `db/ml_read.py` hard-codes the
   subset of ML's `matches` columns the backend reads. [0028](0028-galleries-and-download.md)
   and the `ml_read.py` docstring both promise a **Phase-7 contract test** so an ML
   schema change that drops/renames a consumed column fails backend CI loudly instead
   of at runtime.

Plus **CI/compose parity**: `ci.yml` only greps ML's pure layers and only builds the
ML image, and the gated DB tests (the Postgres repos + the Phase-6 reader) never run
in CI because no job provides a database.

This phase is **pure hardening**: **no migration, no schema change, no ML-service
change** (the contract test only *reads* ML's model + the live catalog).

## Decisions

### 1. Backend HTTP metrics (`observability/metrics.py` + middleware + `/metrics`)

- New `backend/observability/metrics.py`, mirroring the ML service's module shape
  (module-level collectors on the default registry, a `render_latest() ->
  (bytes, str)` for the scrape endpoint). Two collectors:
  - `backend_http_requests_total` — Counter, labels `(method, route, status)`.
  - `backend_http_request_duration_seconds` — Histogram, labels `(method, route)`,
    coarse buckets from 5 ms to 10 s.
- **Cardinality safety is the whole point** (req §13 note, mirrored from ML): `route`
  is the **route template** (`/v1/events/{event_id}/students`), **never** the concrete
  path (`/v1/events/abc-123/students`), and **never** `student_id`/`media_id`. FastAPI
  sets `request.scope["route"]` after routing resolves; the middleware reads
  `route.path` *after* `call_next`. Requests that match no route (404 scanners) carry
  a single fixed `__unmatched__` label instead of their raw path. `method` is likewise
  **clamped** to the registered HTTP verbs (unknown tokens → `OTHER`), so neither label
  dimension is attacker-growable.
- Wiring lives in `main.py` (the only place allowed to, per layering):
  - an `@app.middleware("http")` that times each request and records method / route
    template / status in a `finally` (so an unhandled 500 is still counted);
  - a `GET /metrics` route returning `Response(body, media_type=content_type)` from
    `metrics.render_latest()` — identical to the ML service's endpoint.
- Adds the `prometheus-client>=0.20` dep to `services/backend/pyproject.toml` (same
  floor as ML).

### 2. CORS via `BE_CORS_ORIGINS`

- New setting `cors_origins: str = ""` — a **comma-separated allow-list**, empty by
  default (so nothing changes for non-browser callers / tests). `main.py` parses it
  and, **only when non-empty**, adds Starlette's `CORSMiddleware`
  (`allow_credentials=True`, all methods/headers). Added **after** the metrics
  middleware so CORS is the outermost layer — preflight `OPTIONS` short-circuit there
  and don't inflate request metrics.
- **`"*"` is rejected at startup** (raises `ConfigurationError`, the repo's fail-loud
  config pattern — cf. the empty `jwt_secret`). Because we set `allow_credentials=True`,
  a wildcard origin makes Starlette *reflect and trust any origin* (setting
  `Access-Control-Allow-Credentials: true` for it), which would let any site read
  authenticated responses. Operators must list explicit origins.
- `.env.example` **defaults** `BE_CORS_ORIGINS` to the local FE dev origins
  (`http://localhost:3000` + the `127.0.0.1` form) so the FE works after
  `cp .env.example .env`; the compose `backend` service passes it through
  (`${BE_CORS_ORIGINS:-}`, empty when unset).

### 3. The `matches` contract test (guards the Phase-6 read coupling)

Two tests, one file (`tests/adapters/test_ml_read_contract.py`):

- **`test_matches_columns_match_ml_model` — always runs, no DB.** Imports the ML
  service's authoritative ORM model (`ml_service.db.models.Match`) and the backend's
  `db.ml_read.matches`. Asserts every column the backend reads exists on
  `Match.__table__` with a **compatible type family** (uuid / string / number / bool).
  This is the primary guard — it runs in the normal `check` job on every push and
  fires the instant an ML dev renames or drops a consumed column. (ML's model mirrors
  ML's migrations by that service's working rule, so model drift ≈ migration drift.)
  The import is safe and light: `ml_service.db.models` pulls in only SQLAlchemy +
  `ml_service.db.base`, no faiss/insightface.
- **`test_matches_columns_exist_in_live_schema` — gated on `BE_TEST_DATABASE_URL`,
  via `information_schema`.** Honors the letter of [0028](0028-galleries-and-download.md):
  queries `information_schema.columns` for the live `matches` table and asserts every
  consumed column exists with a compatible Postgres `data_type` — validating that the
  SQLAlchemy types in `ml_read.py` realize as the same Postgres type family ML's model
  produces. It **self-provisions** the table from `Match.__table__` when absent and
  drops only what it created, so (like every gated test here) it assumes a disposable
  test DB. It does **not** try to introspect a *migrated* `matches`: the Phase-6 reader
  test (`test_ml_read.py`) sorts first and its fixture drops `matches` to stand up its
  own reduced copy (that test's minimal inserts can't satisfy the migrated table's
  `NOT NULL` columns), so the two gated tests can't share one migrated table. The
  always-on model check above is the reliable drift guard; this one adds the live
  Postgres type cross-check.

### 4. CI/compose parity

- **`ci.yml` layering step** also greps the backend pure layers
  (`backend/domain`, `backend/services`) for concrete IO imports — mirroring the
  backend grep already in `scripts/check.ps1` (the AST gate `tests/test_layering.py`
  stays the thorough check; this is the fast fail-loud mirror).
- **`docker-build` job** also builds the backend image
  (`services/backend/Dockerfile`) — proving both deployment images build. No push.
- **New `integration` job** (Postgres 16 + Redis 7 service containers) runs the full
  suite with `BE_TEST_DATABASE_URL` / `ML_TEST_DATABASE_URL` / `ML_TEST_REDIS_URL`
  pointed at them, so the gated Postgres repo tests, the Phase-6 reader test, and the
  new live-schema contract test actually execute in CI. It applies **both** Alembic
  chains first (backend + ML) as an **apply-and-coexist smoke** — this is the first
  place CI runs `alembic upgrade head`, proving both chains apply and coexist in one DB
  via distinct version tables ([0023](0023-backend-db-schema.md)) — then **resets the
  schema to empty** (`DROP SCHEMA public CASCADE; CREATE SCHEMA public`) before pytest.
  The gated tests **self-provision** their own tables per fixture (the repo tests their
  `Base.metadata`, the reader its reduced `matches`, the contract test the full one) and
  **assume an empty DB**; the reset is what makes that assumption hold. Without it the ML
  migration's `student_media_appearances` **view** (which depends on the detection audit
  tables) blocks `Base.metadata.drop_all` in the ML repo-test teardown — so the reset is
  precisely what makes the gated tests independent of the migrated schema.
- **`docker-compose.yml` `backend` service**: add `redis` (`condition:
  service_healthy`) to `depends_on` and set `BE_REDIS_URL` / `BE_QUEUE_STREAM` /
  `BE_CORS_ORIGINS` — the enqueue path ([0027](0027-events-media-enqueue-status.md))
  needs Redis up, and browsers need CORS. The env vars already exist in `.env.example`
  from Phase 5 (`BE_REDIS_URL`, `BE_QUEUE_STREAM`); this phase adds `BE_CORS_ORIGINS`.

## Alternatives rejected

- **Per-adapter / DB-call metrics.** Same call made for the ML service
  ([0017](0017-docker-observability-ci.md)): instrument at the HTTP boundary only, keep
  the pure layers instrumentation-free. Finer metrics are a documented follow-up.
- **Pure model-to-model contract check only (no DB).** It catches the drift we care
  about, but [0028](0028-galleries-and-download.md) specifically promised a live
  `information_schema` test; the gated variant also validates the Postgres type
  mapping and, in the integration job, the real migrated schema. We keep both — the
  no-DB one as the always-on guard, the gated one as the live cross-check.
- **Reflecting ML's `matches` into the backend at runtime** (instead of the hand-kept
  `ml_read.py` + a test). Rejected in [0028](0028-galleries-and-download.md): runtime
  reflection couples startup to ML's schema and hides the consumed surface. The
  contract test gives the safety without the runtime coupling.

## What this phase does NOT do (deferred, documented)

- **OpenTelemetry tracing** for the backend (the ML service has opt-in OTel). Opt-in,
  two extra deps, marginal v1 value — deferred; the seam is the same
  service-call-boundary pattern when it lands.
- **Rate limiting, security headers, request-id/access-log middleware, server-side
  upload-size enforcement** (the last already flagged a follow-up in
  [0026](0026-students-and-ml-enrollment.md)). None are v1-blocking.

## Testing

- `test_ml_read_contract.py` (both tests above).
- `test_metrics.py` — a `TestClient` smoke test: `GET /metrics` returns 200 with the
  Prometheus content type and the two collectors; a request to a **parametrized**
  protected route (unauthenticated → 401, but the route matches first) records the
  route-**template** label with the concrete id absent; an unmatched path collapses to
  `route="__unmatched__"`.
- `test_cors.py` — with `BE_CORS_ORIGINS` set, a request with an allowed `Origin` gets
  the `access-control-allow-origin` header; with the setting empty, no CORS headers;
  with `"*"`, `create_app()` raises `ConfigurationError`.
- `test_ml_read_contract.py` also unit-tests the `_family` helper across every type
  branch (uuid / string / number / bool / int).
- Full gate green after each review round: `ruff` + `mypy` + layering (grep + AST) +
  `pytest`.

## Files

- **New:** `services/backend/src/backend/observability/metrics.py`;
  `services/backend/tests/{test_metrics.py,test_cors.py}`;
  `services/backend/tests/adapters/test_ml_read_contract.py`.
- **Changed:** `services/backend/src/backend/main.py` (metrics middleware + `/metrics`
  + conditional CORS); `services/backend/src/backend/settings.py` (`cors_origins`);
  `services/backend/pyproject.toml` (`prometheus-client`); `.env.example`
  (`BE_CORS_ORIGINS`); `docker-compose.yml` (`backend` redis dep + env);
  `.github/workflows/ci.yml` (backend layering grep + backend image build +
  `integration` job); `scripts/check.ps1` (grep mirror gains `storage3`/`pydantic`);
  `CLAUDE.md`; `decisions/README.md`.
- **No migration. No ML-service change.**

## Follow-up (2026-07-12): integration-job schema reset

The first CI run of the new `integration` job failed: the ML gated repo tests
(`services/ml_service/tests/adapters/test_postgres_repos.py`) errored in fixture
teardown with `cannot drop table face_detection_candidates because other objects
depend on it` — the migration-created `student_media_appearances` **view**. Root cause:
the job applied both Alembic chains and then ran the gated tests **in the same DB**, but
those fixtures self-provision via `Base.metadata.{create,drop}_all` and assume an empty
DB. The migrated ML view (not part of `Base.metadata`) depends on the detection tables,
so `drop_all` couldn't drop them. The doc's original claim that the gated tests are
"independent of the migrated tables" was aspirational — nothing enforced it.

Fix: after the apply-and-coexist smoke, **reset the schema to empty**
(`DROP SCHEMA public CASCADE; CREATE SCHEMA public`, via `psql`) before pytest, so the
gated fixtures get the empty DB they assume. `postgresql-client` was added to the job's
apt install to guarantee `psql`. This is a CI-only change (still no migration, no
application-code change); §4 above is updated to describe it. (A local-dev caveat
remains: pointing the gated ML repo tests at a DB that already has the ML migrations
applied hits the same view-dependency — the tests assume a *disposable, empty* DB.)
