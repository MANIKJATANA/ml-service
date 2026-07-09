# 0025 — Platform + school onboarding, teacher limits (Phase 3)

**Date:** 2026-07-09
**Status:** Accepted

## Context

Phase 2 ([0024](0024-auth-jwt-and-rbac.md)) delivered auth + the RBAC seam
(`require_permissions`) but no protected feature routes. Phase 3 lands the first
ones — the onboarding flow the product opens with ([0022](0022-backend-architecture-and-scope.md)):

- **We** (platform operators, `platform_admin`) onboard **schools** and set each
  school's `max_teachers`, then provision the school's first **`school_admin`**.
- The **`school_admin`** logs in and creates **teacher** accounts, up to
  `max_teachers`.
- Staff can be **listed** so an admin sees the roster.

Students, events, media, and galleries are later phases; this phase is purely
identity/tenant provisioning on top of the Phase-1 `schools`/`users` tables — **no
schema change**.

## Decisions

### Routes (all behind `require_permissions`)

Platform operators (`school:manage`):

| Method + path | Purpose |
|---|---|
| `POST /v1/schools` | create a school `{name, max_teachers}` |
| `GET /v1/schools` | list all schools |
| `GET /v1/schools/{school_id}` | fetch one (404 if absent) |
| `POST /v1/schools/{school_id}/admins` | provision a `school_admin` `{email, password}` |

School admins (`staff:manage`):

| Method + path | Purpose |
|---|---|
| `POST /v1/staff` | create a `teacher` `{email, password}` in the caller's school (cap-enforced) |
| `GET /v1/staff` | list the caller's school's teachers |

### Tenant isolation is derived from the token, never the request

The single rule that keeps schools apart: **school-scoped operations take
`school_id` from the authenticated user (`current_user.school_id`), not from the URL
or body.** A `school_admin` cannot target another school because their token fixes
their tenant — `POST /v1/staff` has no `school_id` parameter at all. Platform routes
are the deliberate exception: a `platform_admin` (null `school_id`) operates across
tenants, so those routes take `school_id` in the **path**. (A `school_admin` reaching
a `/v1/schools*` route is stopped earlier by `require_permissions`.)

### `max_teachers` caps teachers only; enforced in the service

The cap counts **`teacher`** accounts only (`school_admin`s don't count —
[0022](0022-backend-architecture-and-scope.md) baked default). `OnboardingService`
enforces it: read the school, count its teachers, reject with `LimitExceededError`
(→ **409**) when `count >= max_teachers`, else create. The count-then-create is two
statements, so a race could momentarily exceed the cap; this is **accepted for v1**
(a school has a single admin doing sequential creates — the same single-writer
reasoning as the ML service's FAISS Option A) and documented. The tightening (a
`SELECT … FOR UPDATE` on the school row, or a counting trigger) is a scale follow-up.

### Provisioned accounts use a caller-set temp password

There is no SMTP in v1, so the **creator supplies the initial password** in the
request; the account is created with `must_change_password=true` (Phase 2 flag) and
the password is **never echoed back**. The `school_admin` hands the temp password to
the teacher out of band; the teacher changes it on first login via
`POST /v1/auth/change-password`. Same pattern for a `platform_admin` provisioning a
`school_admin`.

### Business logic in one service; RBAC stays at the route

`OnboardingService` (`services/onboarding_service.py`) depends only on
`SchoolRepository`, `UserRepository`, and `PasswordHasher` (ports) — no RBAC, no HTTP.
It hashes the supplied password, validates the target school exists (and is `active`
for teacher creation), enforces the cap, and delegates uniqueness to the repo
(`ConflictError` on duplicate email). Authorization is enforced once, at the route,
by `require_permissions(...)`; tenant scoping by passing the token's `school_id` in.

### Repository + schema surface

- **`UserRepository`** gains `count_by_school_and_role(school_id, role) -> int` and
  `list_by_school_and_role(school_id, role) -> list[User]` (ordered `created_at, id`).
  No new columns → **no migration** this phase.
- A shared **`UserResponse`** (`api/schemas/users.py`, `id/email/role/school_id/
  status/must_change_password`, never the hash) is the public user shape for the new
  routes; `/v1/auth/me` is switched to it so there is one such model, not two.
- **`SchoolResponse`** mirrors the `School` domain model.

### Validation

`name` non-empty (≤200); `max_teachers` an int `>= 1` (`<= 100000` sanity bound);
provisioning passwords `>= 8` (≤1024, the Phase-2 argon2-DoS cap). Creating staff for
a **suspended** school is rejected (`ValidationError` → 400).

### Domain error

`LimitExceededError(BackendError)` → **409**, mapped centrally in `main.py`.

### Test doubles are shared now

Phase 2 hand-rolled `FakeUserRepo` in two test files. Phase 3 needs it plus a
`FakeSchoolRepo` in more places, so the doubles move to
`services/backend/tests/backend_fakes.py` (uniquely named to avoid a `fakes` module
collision with the ML service under `--import-mode=importlib`), imported via a new
`tests/conftest.py` `sys.path` insert — the pattern the ML service already uses. The
two Phase-2 test files are refactored onto it.

## Consequences

- The platform can onboard schools and provision the full staff hierarchy end to
  end, all authorized + tenant-isolated; Phase 4 (students + ML enrollment) builds on
  `school_admin`/`teacher` accounts existing.
- `require_permissions` gains its first real route consumers, exercising the RBAC
  seam over HTTP.
- No schema migration; the two `count`/`list` reads are the only new repo surface.

## Alternatives rejected

- **Create the school + its first `school_admin` in one `POST /v1/schools`** —
  rejected: the two writes span two repositories (schools, users) with no shared
  unit-of-work, so a duplicate-admin-email would orphan a freshly-created school.
  Two explicit endpoints keep each write atomic; a school briefly without an admin is
  a benign transient the operator resolves.
- **`school_id` in the path for staff routes** (with a server-side check that it
  equals the token's) — rejected as needless surface: deriving it from the token is
  strictly safer (nothing to forge) and simpler.
- **A DB-enforced teacher cap now** (trigger / `FOR UPDATE`) — deferred: unjustified
  complexity for a single-writer-per-school workload; the service check + documented
  race is sufficient for v1.
