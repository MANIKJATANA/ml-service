# 0057 — Product Build BP10: Bulk photo enrollment

**Date:** 2026-07-25
**Status:** Accepted

## Context

BP7d (CSV import, [0047](0047-product-build-BP7d-csv-bulk-import.md)) creates students
**photoless → `pending`**; BP7d-2 ([0048](0048-product-build-BP7d2-reference-photo-replace.md)) added a
face **one student at a time** (`PUT /v1/students/{id}/reference-photo` → set + BP17 thumbnail + re-enroll).
For a real school that means ~800 manual uploads to switch matching on — the Round-2 review's highest-severity
finding (theme A, the "enrollment wall"; `04` §BP10, lenses X4/T8/P5). The product can't be turned on at scale.

BP10 delivers **bulk reference-photo enrollment** — a filename-mapped multi-photo upload that enrolls a whole
class in one pass — plus a one-click **retry** for a batch of failed enrollments.

## Decision

Build BP10 on the primitives that already exist. The whole feature adds **one read endpoint + one cleanup
endpoint + one repo method** to the backend; the upload-and-enroll loop runs on the **frontend** (a bounded
pool over the already-tested per-student routes, exactly the pattern `useMediaUpload` uses for event media).

### Backend

- **`StudentRepository.resolve_by_emails(school_id, emails) -> list[Student]`** — one tenant-scoped,
  case-insensitive `WHERE lower(users.email) IN (…)` lookup joined to `users`. The UUID branch reuses the
  existing `list_by_ids`.
- **`StudentService.resolve_photo_targets(school_id, filenames) -> list[ResolvedPhotoTarget]`** — pure
  orchestration: strip each filename to its stem (drop a known image extension), partition stems into UUIDs
  (match by `student_id`) vs emails (match by email), look both up tenant-scoped, and return one
  `ResolvedPhotoTarget(filename, student|None)` per input. A filename that names no student *in this school*
  is returned unmatched (never a cross-tenant probe).
- **`StudentService.delete_reference_photo_upload(school_id, object_path)`** — the same
  `_require_tenant_photo_path` prefix guard (a caller can only ever address an object under
  `{reference_photo_prefix}/{school_id}/`) then a **best-effort** `ObjectStore.delete` (a store blip or
  missing key is logged + swallowed, never surfaced — the FE fires this fire-and-forget). For orphan cleanup.
- **`POST /v1/students/match-photos`** (`student:manage`, tenant from the token) — the read that auto-fills
  the FE mapping table. The request `filenames` list is capped at the configurable
  `settings.bulk_photo_max_files` **in the schema** (`Field(max_length=…)` reading settings, mirroring
  `api/pagination.py`), so an over-size batch is a free **422**.
- **`DELETE /v1/students/reference-photo-upload?path=…`** (`student:manage`, tenant from the token) — the
  orphan cleanup, guarded to the caller's own prefix (a foreign path is a **400**), idempotent.
- **`BE_BULK_PHOTO_MAX_FILES`** (default **50**) → `settings.bulk_photo_max_files` + `.env.example`.
- The per-student **`PUT …/reference-photo`** and **`POST …/enroll`** are **unchanged and reused** — they
  already do photo-set + thumbnail + old-object cleanup + ML enroll (and enroll-retry), tenant-guarded.

### Frontend

- **Bulk photo dialog** (`components/students/bulk-photo-dialog.tsx`) — a 3-step **pick → map & fix →
  results** dialog. The browser **holds the picked `File` objects**; on pick it sends only the filenames to
  `matchPhotos`, then shows an **editable mapping table**: each auto-matched row can be **changed**, each
  unmatched photo **assigned** a student, or **left unmatched to skip it**. A student already assigned to
  another photo in the batch is disabled (no accidental double-assign). Enforces the batch cap.
- **Student picker** (`components/students/student-picker.tsx`) — a single-select, type-to-search picker
  (Radix `Popover` + `SearchInput` + `useStudents({q})`), modelled on BP5's "Add students"
  (`appearance-editor.tsx`). Searches via the existing `GET /v1/students?q=`; **no new endpoint**.
- **`useBulkPhotoEnroll`** (`lib/hooks/use-bulk-photo-enroll.ts`) — a bounded-concurrency pool (adapts
  `useMediaUpload`): only **after confirm**, and only for photos **with an assigned student**, per item does
  `uploadReferencePhoto(file)` (mint → PUT straight to Supabase) → `setStudentReferencePhoto(studentId,
  path)`. If the PUT succeeds but the attach **throws** (student gone / transient), the browser best-effort
  `deleteReferencePhotoUpload(path)` — no orphan. (A returned `enrollment_status: failed` is **not** an
  attach failure — the photo *is* attached, so the object is kept.)
- **Retry failed** — a "Retry failed (N)" control on the students list (N from the dashboard rollup) pages
  the `failed` students and loops the existing `POST …/enroll` through a small pool. No new endpoint.
- **`NEXT_PUBLIC_BULK_PHOTO_MAX_FILES`** (default 50) mirrors the backend cap for the pre-upload UX; the
  backend `match-photos` schema is the authoritative enforcement.

### The filename → student matching rule

`aisha@greenfield.edu.jpg` → drop a known image extension → stem `aisha@greenfield.edu`. If the stem is a
valid UUID → match by `student_id`; else → match by **email** (case-insensitive, exact) within the school.
No match → **unmatched** (surfaced, never uploaded). Email is the recommended convention.

## Why

- **Reuse over rebuild.** Each photo must be uploaded browser→Supabase anyway (we never route image bytes
  through the backend); since the upload is already client-side and per-file, the enroll rides along right
  after — the exact `useMediaUpload` pattern. So the enroll/upload path is the already-tested
  `set_reference_photo`, and the only net-new backend logic is a read (matching) + a guarded delete (cleanup).
- **Match on the backend, not the browser.** Sending only filenames (≤50 short strings) keeps the 800-email
  roster off the wire (scale-friendly, consistent with BP9) and keeps the matching rule + tenant isolation in
  one place. The auto-match is a *starting point*: the editable table lets staff correct any row or handle a
  weirdly-named file, so a mismatch never blocks enrollment.
- **Upload-after-confirm + only-assigned = no orphans by construction.** Unmatched/skipped photos are never
  uploaded, so there is nothing to clean up for them. The cleanup endpoint exists only for the rare
  uploaded-then-attach-failed case (e.g. the student was deleted mid-batch), honouring the owner's "removed
  from Supabase if saved" requirement.
- **Retry targets `failed`, not `pending`.** A `failed` student already has a photo (a blip — e.g. ML was
  briefly down), so a retry can fix it; a photoless `pending` student has nothing to enroll and belongs to
  the bulk *photo* flow. Clean separation.

## Security

- **`match-photos` is tenant-scoped** (only the caller's school). An email from another school returns
  "unmatched" — no cross-tenant enumeration, no leak. The caller (`student:manage`) can already list every
  in-school student + email, so no new information is exposed.
- **The cleanup delete is prefix-guarded** to `{reference_photo_prefix}/{school_id}/`. It is a new primitive
  ("delete a bare object under my school's prefix"); the incremental risk (an admin deleting another
  *in-school* student's reference-photo object, leaving a dangling DB path) sits **within the caller's
  existing `student:manage` destructive authority** — they can delete that student outright — and is
  tenant-bounded and recoverable (re-upload). Object keys are unguessable UUIDs. Documented, accepted.
- **Defense in depth:** even a crafted `match`/enroll can't touch a foreign student or path — the per-student
  `PUT …/reference-photo` re-checks the tenant (foreign → 404) and the object-path prefix guard.
- An **ML outage never blocks** account creation/enrollment ([0026](0026-students-and-ml-enrollment.md)): a
  failed enroll is a recorded, retryable `failed` state per row.

## Alternatives considered

- **A server-side batch enroll endpoint** (POST a list of `{student_id, path}` → loop `set_reference_photo`
  server-side). Rejected: the browser must upload each file to Supabase anyway, so the loop is already
  client-side; a batch endpoint would duplicate the per-file work without removing a round trip, and lose the
  natural per-file progress. A background/queued job is the documented scale-up if register-time latency on
  huge batches matters.
- **A `GET /students/roster` for the FE to match client-side.** Rejected: ships all 800 emails to the browser
  (against BP9's grain) and re-implements matching on the FE. Backend `match-photos` sends only filenames.
- **Upload everything first, then map.** Rejected: wastes uploads on mis-named files and orphans objects.
  Upload-after-confirm + only-assigned avoids both.
- **No cleanup endpoint (rely on storage lifecycle reaping, the event-uploader precedent).** Rejected in
  favour of the explicit tenant-guarded delete, per the owner's "removed from Supabase if saved" ask; the
  lifecycle policy remains the backstop.
- **Multi-select bulk archive/delete on the lists.** Out of scope — that is BP13. BP10's bulk actions are
  enrollment-only.

## Consequences

- **No migration, no ML change, no new dependency, no new permission** (reuses `student:manage`). One new
  env var (`BE_BULK_PHOTO_MAX_FILES`, + the FE `NEXT_PUBLIC_` mirror).
- **Honest limits (documented):** batch capped at 50 (configurable) — a 500-student class is ~10 batches; the
  client-side loop makes 500 enrollments 500 throttled ML calls (a background job is the scale-up); "Retry
  failed" only rescues photo-present failures (a `no_face` won't self-heal — it needs a replacement photo);
  the student picker is Tab-navigable but has no arrow-key roving (consistent with BP5's "Add students"
  popover — an accepted v1); the bulk dialog is **non-modal** so the per-row picker's list scrolls by
  wheel/trackpad (a modal Dialog's `react-remove-scroll` lock blocks wheel on a portaled popover — only the
  scrollbar-drag works), with the accepted trade-off that focus isn't trapped; local-fs dev has no real
  Supabase byte I/O, so the live upload path is only exercised against a running stack (same caveat as BP17).
- **Verification:** BE ruff + mypy + pytest + layering; new unit tests (matcher email/UUID/case-insensitive/
  unmatched/foreign-tenant/already-enrolled; the batch-cap 422; the cleanup prefix guard; the two routes) + a
  gated real-Postgres `resolve_by_emails` round-trip on a **throwaway** DB (never the dev `app` DB). FE lint +
  tsc + `next build`. 2× review→fix loop, gate green after each, then stop for owner review. No commit/push
  without an explicit request.
