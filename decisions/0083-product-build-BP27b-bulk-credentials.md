# 0083 — Product Build BP27b: Shown-once bulk credentials (student resend + staff CSV invite)

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review→fix loop clean). **Committed 27a separately (`1c8f1d1`); 27b not
  yet committed** (awaiting owner review).
- **Phase:** **BP27b** — the second slice of **BP27 (Bulk operations parity)**, Round-4 findings **R4-A05** (no bulk
  credential resend) + **R4-A13** (no bulk staff invite). **BE + FE — no migration, no ML change, no new dependency, no
  new permission, no new env var.**

## Context

The **shown-once bulk-credentials** slice, pulled out of 27a on the plan-review's advice so the plaintext-secret
surface is designed + reviewed on its own. Two features that share one FE `BulkCredentialsDialog`:
- **Student bulk-resend-invite** — resend a fresh one-time temp password to many locked-out students at once (the
  bulk form of BP18a's recovery-without-the-destructive-delete).
- **Staff CSV bulk invite** — invite many teachers from an email CSV (the staff form of BP7d's student importer).

Both **return N plaintext temp passwords at once**, so the whole slice is governed by a **shown-once secret
contract**: the plaintext appears only in the response body, on success rows only, generated per-row + hashed
immediately by the reused single-writers, never persisted plaintext, never re-fetchable, **never logged**.

**Workflow (owner-directed multi-agent pipeline, per slice):** planning agent (consolidated the 27b spec) →
**security-first** plan-review agent (8 hardenings, 0 blockers) → implementation agent (built + gated) → 2× review
loop (R1 correctness+security, R2 edge/a11y/copy).

## Decision (all composing tested single-writes)

### Backend — two best-effort loops (the batch never aborts)
- **`StudentService.bulk_resend_invite(*, school_id, student_ids) -> list[BulkResendResult]`** — loops the existing
  `resend_invite`; per row `{student_id, email, status: sent|error, temp_password?}`. On success →
  `(sid, prov.student.email, "sent", temp_password)`; on **any** exception → `(sid, "", "error")`. **The error row
  carries `email=""` because `resend_invite`'s tenant-scoped `get_student` 404s a foreign/missing id BEFORE any
  student is resolved — the loop never reads an email on the failure path** (a foreign id must never confirm an
  address). Not active-school-gated (recovery must work on a suspended school). Reuses the 27a `BulkIdsRequest` cap
  (1000). Behind `POST /v1/students/bulk-resend-invite` (`student:manage`, `tenant_of`, before `/{student_id}`).
- **`OnboardingService.bulk_create_staff(*, school_id, emails) -> list[BulkStaffResult]`** (teacher-only — no `role`
  param): a pre-loop `get_school` + suspension check (`ValidationError` → 400 for the whole batch), then per email
  **two separate try/excepts** (so the two `ValidationError` sources don't collapse): (1) `validate_email` →
  `invalid` (+ the short reason), (2) `create_teacher` catching `LimitExceededError→limit_reached`,
  `ConflictError→duplicate` (**the exception message is discarded — a bare `"duplicate"`, so a global-uniqueness
  collision never leaks a cross-tenant fact**), `ValidationError→error` (a mid-batch suspension), else `error`.
  `temp_password` on `created` only. The **cap re-counts per call** (`count_by_school_and_role`), so the loop fills
  to `max_teachers` then returns `limit_reached` for the rest. New `_MAX_BULK_STAFF = 100` module const (not env).
  `BulkStaffRequest.emails` is `list[str]` (not `list[EmailStr]`) so one bad address is a per-row `invalid`, not a
  422 that rejects the file. Behind `POST /v1/staff/bulk` (`staff:manage` — **admin-only**, `tenant_of`, 201, before
  `/{user_id}`).
- The result VOs are `@dataclass(frozen=True, slots=True)` in their service modules (import-pure, layering-safe),
  `temp_password: str | None = None` default so a row that omits it is structurally `None`.

### Frontend — one shared shown-once dialog + two entry points
- **`components/credentials/bulk-credentials-dialog.tsx`** (shared): a results table (email · result pill · the
  one-time password), an emphasized **"Download credentials" CSV** (`toCsv`/`saveCsv`, promoted to `lib/csv.ts`),
  a **per-row Copy button** (R2 — for the common 1–2 row resend), a **close-guard** keyed on
  `results.some(r => r.tempPassword) && !downloaded` (so an all-`error`/`duplicate` batch closes freely), and
  `reset()` **drops the passwords from state** on close. `limit_reached` → an "At capacity" pill; an `invalid`/`error`
  row shows the **server reason** (R2); a `duplicate` shows a note that the email may exist at another school (R2 —
  the global-uniqueness footgun, disclosed since it isn't a leak but is confusing).
- **Students bar** gains a **"Resend credentials"** action (`bulkResendStudentInvites(targetIds)` → the dialog;
  clears the selection but does **not** revalidate the list — resend changes no list-visible field; a single
  `bulkAction` spins only the clicked button).
- **Staff page** gains a **CSV importer** (`components/staff/bulk-invite-dialog.tsx`: pick → preview[flag
  invalid/duplicate advisorily] → results → the shared dialog) that **`mutate()`s the roster** (it creates rows) and
  toasts honestly ("Created N of M teachers · K at capacity").
- `lib/csv.ts` exports `saveCsv` + `EMAIL_RE` (moved out of the student importer, now shared) + `parseStaffCsv`
  (email-only). `lib/api/{types,endpoints}.ts` add the response types + `bulkResendStudentInvites` / `bulkCreateStaff`.

## Security invariants (verified — R1 SHIP)

- **Shown-once:** the plaintext is present ONLY on `sent`/`created` rows (VO defaults + every append path checked);
  generated per-row, hashed immediately by the reused single-writers, never persisted plaintext, never re-fetchable;
  the FE drops it on close. **No log call includes the password** — resend logs `student_id` only, staff logs `email`
  only, and the `ConflictError` message is caught + discarded (never logged, never returned).
- **Tenant isolation:** `school_id` from `tenant_of(actor)` (token), never body; each `resend_invite`/`create_teacher`
  is tenant-scoped, so a foreign id → `error` with no password and no email echoed, never a cross-tenant write.
- **Best-effort:** one failing row (foreign id / duplicate / ML-independent) never aborts the batch.
- **AuthZ:** `student:manage` (admin+teacher) for resend; `staff:manage` (**admin-only** — a teacher token 403s) for
  staff-bulk. Both tested.

## Files changed (12 modified + 3 new)
Backend: `services/{student_service,onboarding_service}.py` · `api/schemas/{students,users}.py` ·
`api/routers/{students,staff}.py` · **new** `tests/test_bp27b_credentials.py` (21 tests). Frontend:
`lib/csv.ts` · `lib/api/{types,endpoints}.ts` · `components/students/bulk-import-dialog.tsx` (imports the shared
`saveCsv`/`EMAIL_RE`) · `app/(school)/{students,staff}/page.tsx` · **new** `components/credentials/bulk-credentials-dialog.tsx`
· **new** `components/staff/bulk-invite-dialog.tsx`.

## Verification

- **Backend:** ruff clean · mypy clean (173 files) · **pytest 656 passed / 47 skipped** (gated PG/Redis skip without
  `BE_TEST_DATABASE_URL`) · layering clean. The 21 BP27b tests prove: password-only-on-success (both endpoints,
  service + route); the resend foreign-id `email=""` + no-password + batch-continues + foreign-account-untouched;
  staff duplicate (same-school **and** cross-school) / invalid / **cap-partial (max=2, 1 existing, invite 3 → 1
  created + 2 limit_reached)** / suspended-pre-raise; the **teacher-403-on-`/staff/bulk`** case; student-403 /
  401 / over-cap-422 / empty-422; and the route-ordering regression.
- **Frontend:** lint + tsc + `next build` clean; `/staff` + `/students` stay `○` (static).
- **2× review→fix loop:**
  - **R1 (correctness + security): SHIP, 0 blockers, 0 should-fix.** Verified the shown-once VO defaults + every
    append path, the no-secret-in-logs grep, the `ConflictError`-message-discard, the resend `email=""` invariant,
    tenant scoping on both paths, the cap re-count, route ordering + admin-only gating, and that 21/21 tests prove
    the claims. Two optional NITs (no action).
  - **R2 (edge/a11y/copy): 0 blockers.** Applied its 3 should-fixes: a **per-row Copy button** (the small-resend
    ergonomics gap, mirroring the single `InviteResultDialog`), **surfacing the server `invalid`/`error` reason**
    (the API sends it; the FE was dropping it), and the **global-`duplicate` disclosure** note. The all-error
    close-guard, honest mostly-`limit_reached` copy, and N=1 pluralization were confirmed sound.

## Honest limits (documented)

- **Shown-once, no bulk re-fetch:** a lost bulk credential is only recoverable one-at-a-time (single resend). The
  close-guard + Download-CSV + per-row Copy mitigate a stray dismissal.
- **The global-uniqueness footgun:** a staff `duplicate` can mean the email exists at **another** school (emails are
  globally unique). Not a leak (no cross-tenant fact returned) but disclosed in the dialog so it isn't confusing.
- **Cap partial-success:** a 100-row CSV against a `max_teachers=20` school legitimately yields ~80 `limit_reached`
  rows — surfaced distinctly ("At capacity") + honest toast.
- **Preview flags are advisory** — the server's per-row verdict is authoritative.
- **A large `all`-mode resend** renders many one-time passwords in one modal (scrollable; Download-CSV is the
  intended save path) — the per-row Copy suits the small case, Download the large one.

## Next

- **27c** — bulk-photo **retry-failed** + **overwrite-confirm** (R4-A07) + **bulk-remove-from-class** (R4-A10) — the
  last BP27 slice. Then the remaining Round-4 tiers (BP28 governance/audit · BP29 teacher coherence · BP30 review
  tools · BP31 onboarding/copy). A phase/slice starts only on owner pick + scope re-confirm.
