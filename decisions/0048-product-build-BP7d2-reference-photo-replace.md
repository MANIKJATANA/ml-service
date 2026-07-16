# 0048 — Product Build BP7d-2: Reference-photo set/replace

**Date:** 2026-07-16
**Status:** Accepted

## Context

The deferred follow-up from BP7d ([decisions/0047](0047-product-build-BP7d-csv-bulk-import.md)). BP7d made students
importable from CSV (name+email → **photoless, pending**) but left them **unable to enroll** — there was no way to give
a bulk student a reference photo. It also left BP7b's loop open: a `no_face`/`error` enrollment failure could only be
"fixed" by delete-and-re-add. BP7d-2 adds **in-place reference-photo set/replace**, which does both. **Backend +
frontend; NO migration** (the column is already nullable from `0008`), no ML change. Completes **BP7**.

## Decisions

### 1. `PUT /v1/students/{id}/reference-photo` → set the path + (re-)enroll
`StudentService.set_reference_photo` mirrors create's flow: **tenant-scoped `get_student` first** (a foreign/missing
student is 404 **before** the path is inspected — no cross-tenant probing), then the same `_require_tenant_photo_path`
prefix guard, then `StudentRepository.set_reference_photo` (a new port method, structurally identical to
`set_enrollment`), then `_run_enroll` (which sets/**clears** `enrollment_failure_reason` exactly as create does), then
`_reload` with a fallback carrying the just-set path. Route gated by `student:manage`, tenant from the token, body is
just the object path from the existing `POST /v1/students/upload-url` (bytes never touch the backend).

### 2. Frontend — an "Add photo" / "Replace photo" dialog on the student detail
A `ReferencePhotoDialog` (mirrors the create dialog's upload logic — `uploadReferencePhoto` → `setStudentReferencePhoto`
→ refresh the detail + list caches), labelled **"Add photo"** for a photoless student and **"Replace photo"** otherwise.
The uploaded object path is memoized so a failed backend PUT retries without re-uploading. **Re-enroll is hidden for a
photoless student** (it would 400) — "Add photo" is the path to enrollment. The BP7b `EnrollmentFailureNote` fix-copy
now points at **"Replace photo"** (retiring the old delete-and-re-add guidance).

## Verification

- BE gate green: ruff + mypy + **full suite 345 passed / 23 skipped**. New: service tests (enrolls a photoless student;
  fixes a failed one — reason cleared; **replaces on an already-enrolled** student; foreign-prefix reject before any ML
  call; tenant-scoped 404) + route tests (enrolls photoless; foreign-prefix 400; **missing-student 404**) + the gated
  real-Postgres `set_reference_photo` round-trip (run green on a throwaway DB at head).
- FE gate green: `tsc --noEmit` + `eslint` + `next build`.
- **2× review→fix loop** (two agents). **R1 (correctness): no blockers, no bugs** — guard order (tenant before path),
  re-enroll/reason semantics, adapter consistency, and the FE upload→set→refresh flow all verified. **R2
  (edge/quality/a11y/copy)** confirmed a11y/edge-cases correct and its items were applied: the stale
  "until BP7d adds replace" comment, the fallback's leftover "delete and re-add" tail, the upload-path **memo** (parity
  with the create dialog — the backend-PUT failure is the exact retry trigger), and the two cheap test guards above.

## Follow-ups

**BP7 (Onboarding & bulk) is now complete (a, b, c, d, d-2).** Optional later: a student **resend-invite** (lost bulk
credentials currently need delete/recreate); a reference-photo **preview/thumbnail**; a downloadable CSV template.
**Next: BP8 — Ops & reliability** (per `product/03`).
