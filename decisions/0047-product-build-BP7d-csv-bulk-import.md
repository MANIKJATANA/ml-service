# 0047 — Product Build BP7d: CSV bulk student import + student invite model

**Date:** 2026-07-16
**Status:** Accepted

## Context

The fourth and final BP7 sub-phase — the flagship "bulk setup" (see
[decisions/0044](0044-product-build-BP7a-setup-checklist.md) for the split). Today a class is added one student at a
time, each with a typed password + a reference photo — painful at 30 students. Fails **X4/T5**. BP7d adds **CSV bulk
import** and moves students onto BP7c's **invite model** (server-generated temp passwords). **Owner scope call:
bulk-first** — the reference-photo **set/replace** (so bulk/photoless students can enroll, and BP7b's replace-a-bad-photo
loop closes) is deferred to a **BP7d-2** follow-up. **Backend + frontend; one migration (`0008`); no ML change.**

## Decisions

### 1. `students.reference_photo_path` becomes nullable (migration `0008`)
A bulk-imported student is created from **name + email only** — photoless → `enrollment_status='pending'`, no ML call.
`Student.reference_photo_path` is now `str | None` end-to-end (domain, ORM, `StudentRepository.create`, `StudentResponse`).
The migration's `downgrade()` re-imposes NOT NULL and therefore **fails while any photoless row exists** — documented in the
migration (don't downgrade past a bulk import without backfilling).

### 2. Students join the invite model (server-generated temp passwords)
`create_student` drops the caller `password` (→ **server-generated** via a shared `services/credentials.generate_temp_password`,
extracted so onboarding *and* students mint the same CSPRNG one-time password), makes the reference photo **optional**, and
returns a `ProvisionedStudent` → `ProvisionedStudentResponse {student, temp_password}` (shown once, hash-only persisted).
With a photo it enrolls as before; without, it stays pending. `enroll_student` now **guards a photoless student** (400, no
ML call).

### 3. Bulk import — best-effort, per-row, capped
`POST /v1/students/bulk` (`student:manage`, tenant from the token) loops a shared `_provision_student` (the two-write +
compensating-delete, no enroll) over up to **500** `{name, email}` rows. **Best-effort**: each row is validated and created
independently — a `ConflictError`→`duplicate`, a bad name/email (`validate_email`, a pragmatic regex)→`invalid`, any other
error→`error`, and the batch **never aborts**; only `created` rows carry a `temp_password`+`student_id`. The active-school
check is a **snapshot** taken once up front (same accepted sequential-writes race as the teacher cap). Returns a
`BulkImportResponse` of per-row results.

### 4. Frontend — optional-photo create, CSV import, credentials export
- **Single create**: drops the typed-password field (server-gen, shown once via the shared `InviteResultDialog`) but **keeps
  the reference photo required** — a photoless *single* student would be stuck pending until BP7d-2, so only bulk takes the
  photoless path.
- **`BulkImportDialog`**: a 3-step flow (pick file → preview parsed rows → results) over a dependency-free CSV parser
  (`lib/csv.ts` — quoted fields, `""` escapes, CRLF/LF, **BOM strip**, header detection) with a **"Download credentials"**
  CSV (name,email,temp_password) for the created accounts.

## Honest limits (documented)

- **Photoless students stay `pending`** until **BP7d-2** adds reference-photo **set/replace** (which also closes BP7b's
  replace-a-bad-photo loop). The bulk dialog says so at every step.
- **No student password-resend** (staff have resend-invite; students don't). If the credentials CSV is lost, recovery is
  delete-and-recreate until BP7d-2 / a future student resend — so the results dialog makes **Download credentials** the
  emphasized action and warns "shown once."

## Verification

- BE gate green: ruff + mypy + **full suite 337 passed / 23 skipped**. New: service tests (photoless create skips enroll;
  bulk created/duplicate/invalid/error isolation; suspended-school rejects the whole batch; enroll-photoless guard) and
  route tests (`{student, temp_password}` shape; photoless-create pending + no ML; bulk per-row results; the **security
  invariant** that every non-`created` row omits `temp_password`+`student_id`; the 500-row cap → 422; empty → 422;
  enroll-photoless → 400) + a **gated real-Postgres** photoless round-trip.
- **Migration `0008` verified up → down → up on a throwaway Postgres** (`bp7d_migtest`, created + dropped; the dev `app` DB
  never touched), with the gated student adapter tests green against it.
- FE gate green: `tsc --noEmit` + `eslint` + `next build`.
- **2× review→fix loop** (two agents). **R1 (correctness + security + migration + CSV): no blockers** — best-effort loop +
  compensating-delete reuse, tenant isolation, temp-password-only-on-created + hash-only + never-logged, the reversible
  migration, and the CSV tokenizer (quotes/CRLF/escapes/header) all verified. **R2 (edge/quality/a11y/coverage)** → applied
  its should-fixes: the **BOM strip** (Excel exports were importing the header as a student), re-pick-same-file after a
  rejected parse, `role="status"` phase announcements, the **Download-primary** button hierarchy for the one-time secret, a
  photoless reminder at results, and the two regression-guard tests (non-created password-null invariant; 500-cap).

## Follow-ups

**BP7d-2**: reference-photo **set/replace** on a student (`PUT /v1/students/{id}/reference-photo` → update + re-enroll) —
enrolls bulk/photoless students and closes BP7b's replace loop. Optional: a **student** resend-invite; a downloadable CSV
**template**; per-row client-side validation in the preview. **BP7 (Onboarding & bulk) is then complete** → **BP8** (per
`product/03`).
