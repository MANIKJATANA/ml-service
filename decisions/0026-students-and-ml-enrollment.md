# 0026 — Students + ML enrollment (Phase 4)

**Date:** 2026-07-09
**Status:** Accepted

## Context

Phase 3 ([0025](0025-onboarding-and-teacher-limits.md)) landed the staff hierarchy
(platform → school_admin → teacher). Phase 4 opens the first **student** surface —
the owner-locked flow from [0022](0022-backend-architecture-and-scope.md) §4/§5:

- Staff (`school_admin` or `teacher`, permission `student:manage`) **create each
  student** with a display name, a **login account**, and **one reference photo**.
- The backend **triggers ML enrollment** for that photo (synchronous HTTP —
  [0009](0009-enrollment-contract.md)); the result is recorded as the student's
  `enrollment_status`.
- Students log in **only to view** (galleries, Phase 6); they get a **staff-set temp
  password** and `must_change_password=true` (no SMTP in v1 — [0022](0022-backend-architecture-and-scope.md) §5).

This phase is the backend's **first outbound integration** (HTTP to the ML service)
and its **first object-storage touch** (minting a Supabase upload URL). The async
inference path (Redis producer, `ml_read.py` result reads) is **not** here — it
belongs to Phase 5/6. Phase 4 enrollment is synchronous HTTP only.

## Owner decisions (this phase)

1. **Reference photo = frontend uploads directly to Supabase via a backend-minted
   pre-signed URL.** The backend never handles the photo bytes: it mints a short-lived
   Supabase **signed upload URL** for a school-scoped object key, the FE uploads
   straight to Supabase, then the FE calls create-student with the returned
   **bucket-relative path**. The **30 MB/photo limit is enforced on the FE** for now
   (the backend returns `max_upload_mb` so the FE knows it); a server-side cap is a
   documented follow-up. This avoids a MediaStore-through-backend proxy and
   `python-multipart`, but the backend does depend on the `supabase` SDK to sign.
2. **Creating a student also creates its login now** — a `students` profile row **and**
   a linked `users` row (`role=student`, temp password, `must_change_password=true`).

## Decisions

### New tables/models: `students` (migration `0003`)

`students` (backend-owned; its `id` string is the `student_id` sent to ML —
[0022](0022-backend-architecture-and-scope.md)):

| column | type | notes |
|---|---|---|
| `id` | uuid PK | string form = ML `student_id` (`matches.student_id`) |
| `school_id` | uuid **NOT NULL** FK `schools.id` `ON DELETE CASCADE` | tenant |
| `user_id` | uuid **NOT NULL UNIQUE** FK `users.id` `ON DELETE CASCADE` | the login account |
| `name` | text NOT NULL | display name |
| `reference_photo_path` | text NOT NULL | bucket-relative path (enroll source) |
| `enrollment_status` | text NOT NULL default `'pending'` | CHECK `in ('pending','enrolled','failed')` |
| `created_at` / `updated_at` | timestamptz | server defaults, `onupdate` |
| index | `ix_students_school (school_id)` | roster listing |

The `enrollment_status` CHECK values stay **in lockstep** with the `EnrollmentStatus`
domain enum (same note as `users.role`). `user_id`'s `ON DELETE CASCADE` is the delete
mechanism (below). Domain `Student(id, school_id, user_id, name,
reference_photo_path, enrollment_status, created_at, updated_at)` — frozen, `str` ids.

### Ports + adapters added (all config-selected, layering-clean)

- **`StudentRepository`** — `create` / `get(school_id, student_id)` (tenant-scoped) /
  `list_by_school` / `set_enrollment(student_id, status)` / — Postgres adapter
  (`postgres` impl). Reads are always school-scoped (a foreign `student_id` → `None`
  → 404), enforcing tenant isolation at the query layer ([0022](0022-backend-architecture-and-scope.md)).
- **`UserRepository.delete(user_id)`** — new method (Postgres + fake). Used both to
  compensate a failed create and to delete a student (via the `user_id` cascade).
- **`ObjectStore`** — `create_signed_upload_url(object_path) -> SignedUpload{upload_url,
  object_path, token}`. Impls: `supabase` (`SupabaseObjectStore`, storage3
  `create_signed_upload_url`, key injected by wiring) and `local_fs`
  (`LocalFsObjectStore`, a credential-free dev stub returning a `file://`-style URL).
  The **object key is chosen by the service** (business concern), not the store.
- **`MlEnrollmentClient`** — `enroll(school_id, student_id, photo_uris) ->
  EnrollmentOutcome{embeddings_stored, photo_results}` and `delete(school_id,
  student_id)`. Impls: `http` (`HttpMlEnrollmentClient`, httpx → the ML enrollment
  API, [0009](0009-enrollment-contract.md)) and `fake` (in-proc, for offline dev/tests —
  mirrors the ML service's `inproc` philosophy). Selecting `local_fs` + `fake` runs
  the whole backend with **no Supabase and no ML service**.

New domain value types (pure): `EnrollmentStatus` (StrEnum), `EnrollmentOutcome` +
`PhotoResult`, `SignedUpload`. New error **`UpstreamError`** (a failed/unreachable ML
call) → **HTTP 502**, mapped centrally in `main.py`.

### `StudentService` orchestrates; RBAC + tenant stay at the route

`services/student_service.py` depends only on ports (`StudentRepository`,
`UserRepository`, `SchoolRepository`, `PasswordHasher`, `ObjectStore`,
`MlEnrollmentClient`) — no HTTP, no RBAC. As with onboarding, authorization is at the
route (`require_permissions(Permission.STUDENT_MANAGE)`) and the tenant is the token's
`school_id`, never the URL/body.

- **`create_upload_url(school_id)`** — object key `{reference_photo_prefix}/{school_id}/
  {uuid4}`; mint the signed URL. The **school_id in the key is from the token**, so a
  caller can only ever get an upload URL under their own tenant's prefix.
- **`create_student(school_id, name, email, password, reference_photo_path)`**:
  1. school exists + `active` (else `ValidationError`→400, same as teacher creation);
  2. **path guard**: `reference_photo_path` must start with
     `{reference_photo_prefix}/{school_id}/` (else `ValidationError`) — stops a caller
     submitting another tenant's / an arbitrary object path;
  3. create the login `users` row (`role=student`, hashed temp password,
     `must_change_password=true`) — a duplicate email raises `ConflictError`→409 with
     **nothing else written yet**;
  4. create the `students` row; **on failure, compensating-delete the just-created
     user** and re-raise (see atomicity note);
  5. **enroll** (best-effort): `ml_client.enroll(..., [reference_photo_path])`;
     `embeddings_stored >= 1` → `enrolled`, else `failed`; an `UpstreamError` (ML down)
     is caught, logged, and recorded as `failed` — the account still returns **201**
     with a visible `enrollment_status` and a re-enroll path. Enrollment availability
     never blocks account creation.
- **`enroll_student(school_id, student_id)`** — re-enroll/retry using the **stored**
  `reference_photo_path`; updates `enrollment_status`. (Replacing the photo is a
  deferred feature; v1's reference path is immutable after create.)
- **`delete_student(school_id, student_id)`** (FR-E2) — fetch (tenant check), then
  **ML delete first** (must succeed, so we never orphan embeddings; ML down → the
  `UpstreamError`→502 surfaces and the operator retries), then `users.delete(user_id)`
  — the `students.user_id` `ON DELETE CASCADE` removes the profile row in the same
  statement.

### Atomicity: compensating action, not a shared transaction

`create_student` does two writes across two repositories (users, then students) with
no shared unit-of-work — the same constraint 0025 hit for schools+admins. We order
**user-first** (the only realistic failure, a duplicate-email `ConflictError`, then
leaves nothing behind) and **compensate** a students-insert failure by deleting the
just-created user. This is honest for v1's single-writer-per-school workload; a proper
shared-transaction UoW is the documented tightening (as with 0025's teacher-cap race).
Delete uses the FK cascade so it's a **single** statement (no compensation needed).

### Routes (`api/routers/students.py`, `student:manage`, tenant from token)

| Method + path | Purpose |
|---|---|
| `POST /v1/students/upload-url` | mint a signed reference-photo upload URL |
| `POST /v1/students` | create student + login + enroll `{name,email,password,reference_photo_path}` |
| `GET /v1/students` | list the caller's school's students |
| `GET /v1/students/{student_id}` | fetch one (404 if absent / other tenant) |
| `POST /v1/students/{student_id}/enroll` | re-enroll / retry |
| `DELETE /v1/students/{student_id}` | delete student + login + ML embeddings (204) |

Schemas (`api/schemas/students.py`): `CreateStudentRequest` (name 1–200, `EmailStr`,
password 8–1024, `reference_photo_path` 1–1024), `StudentResponse` (the profile shape,
never the login hash), `UploadUrlResponse` (`upload_url`, `object_path`,
`max_upload_mb`). A shared `tenant_of(user)` helper moves to `api/deps.py` (fail-closed
on a null school), reused by the student routes.

### Settings + env surface (per the `.env.example` rule)

New `BE_` settings (added to `.env.example` **and** synced to `.env`): `object_store_impl`
(`supabase`), `ml_enrollment_client_impl` (`http`), `supabase_url`, `supabase_key`
(**SecretStr**), `supabase_bucket` (`media` — **must equal `ML_SUPABASE_BUCKET`**),
`reference_photo_prefix` (`reference-photos` — matches the ML prefix split in
[0022](0022-backend-architecture-and-scope.md)), `max_upload_mb` (`30`),
`object_store_dir` (local_fs dev), `ml_http_timeout_s` (`30.0`). Offline dev:
`BE_OBJECT_STORE_IMPL=local_fs` + `BE_ML_ENROLLMENT_CLIENT_IMPL=fake`.

New deps in `services/backend/pyproject.toml`: `httpx>=0.27` (ML client) and
`supabase>=2.0` (signed upload URLs) — both cross-platform.

## Consequences

- Staff can create students, enroll them, re-enroll, and delete them end-to-end,
  authorized + tenant-isolated; the ML enrollment integration is exercised over HTTP.
- The backend gains its outbound HTTP + object-store seams behind ports, so it still
  runs fully local (`local_fs` + `fake`).
- `enrollment_status` gives the UI an honest per-student state without a callback.
- No ML-service change; the enroll/delete contract is exactly
  [0009](0009-enrollment-contract.md)'s.

## Alternatives rejected

- **Multipart photo bytes through the backend** (backend uploads to Supabase) —
  rejected by the owner in favour of a FE-direct upload via a backend-minted signed
  URL: no large-body proxy, no `python-multipart`; the 30 MB guard sits on the FE for v1.
- **Defer student login to Phase 6** — rejected by the owner: create the login now
  (decision 2), so a student is immediately usable once galleries land.
- **A shared-transaction UoW for the two-write create** — deferred: unjustified
  refactor for a single-writer workload; compensating action + FK-cascade delete cover
  v1 (mirrors 0025's accepted-race stance).
- **Blocking account creation on ML enrollment success** — rejected: an ML outage
  would then block onboarding students. We decouple — create always succeeds, the
  enrollment result is a recorded, retryable status.
- **Making `reference_photo_path` optional / photo-later** — rejected for v1: the owner
  flow always uploads one photo at create; a NOT NULL path keeps the model simple.
