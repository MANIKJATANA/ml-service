# 0065 — Product Build BP18a: Student credential recovery

- **Date:** 2026-08-06
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the first slice of **BP18 (Account recovery & credential safety)** — the fix for Round-3
  **Critical #1** ([decisions/0064](0064-product-review-round-3-ux.md), `product/06` theme J). Sliced a–d per
  the owner-approved plan (an HTML explainer `bp18-plan.html` + this decision): **a** = student recovery (this),
  **b** = credential-safety guards + self-service + the student name, **c** = school-record lifecycle,
  **d** = session revocation + student disable (the one migration).

## Context

A student who forgot their password had **no recovery path**: `resend-invite` existed only for staff/admins
(BP7c), and the only student remedy — delete-and-recreate — **permanently destroys their photo history** (BP8e
purges the student's `matches`; the ML worker skips already-`completed` media on reprocess, so a recreated
student id can never be re-matched). At 800 students on paper-slip passwords, forgotten credentials by mid-year
are a certainty, so the product's core promise silently broke for each affected child.

## Decision

Give students the **exact recovery path staff/admins already had** — a fresh one-time temp password, without
touching anything else. A **1:1 port** of `OnboardingService.resend_invite`; **no migration** (reuses the
`users.password_hash` + `must_change_password` columns from `0002`).

- **BE:** `StudentService.resend_invite(*, school_id, student_id)` — `StudentService` already holds
  `UserRepository`, so no wiring change: `get_student` (tenant-scoped → **404 before any write**) →
  `generate_temp_password()` → `users.set_password(student.user_id, …, must_change_password=True)` → returns the
  existing `ProvisionedStudent`. It touches **only** the password: no ML delete, no profile mutation, no
  enrollment change — the student's photos + matches survive. Route `POST /v1/students/{student_id}/resend-invite`
  (`student:manage`, `school_id = tenant_of(actor)`, response `ProvisionedStudentResponse`). Intentionally **not**
  active-school-gated (mirrors staff resend — recovery must work regardless of school status); role is implicit
  (a `students` row's login is a `student` by construction, 0026).
- **FE:** a **"Send new password"** action on the student detail (reuses the shown-once `InviteResultDialog`) +
  `resendStudentInvite` in the API client; a **"Forgot your password? Ask your school"** line on `/login`; and a
  mid-session-expiry cue — `auth-guard` redirects a truly-dead session to `/login?reason=expired`, which the
  login page reads from `window.location.search` in a client `useEffect` (deliberately **not** `useSearchParams`,
  so `/login` keeps prerendering static with no Suspense boundary) → a "You were signed out" toast.

## Why

- **Reuse over new machinery:** the BP7c resend is proven; porting it keeps the crypto/secret handling in one
  shape (server-generated, hashed-only, shown once) and adds no new surface.
- **The service fetch IS the tenant+role guard:** `get_student` resolves a foreign/missing student to 404 before
  any password write, and the `students` table only links `student` logins — so no explicit role check is needed
  (unlike the staff path's `_require_managed_user`, which spans multiple roles).

## Consequences

- A locked-out student is recoverable in one click, **without** the destructive delete. Verified end-to-end at
  the auth layer: create → old temp pw logs in → resend → **old pw 401s, new pw logs in + forces a change** —
  with the student (and their matches) intact.
- **Honest limit (until BP18d):** a resend changes the password so the **old password stops working at login**,
  but an already-issued **refresh token stays valid up to 14 days** — BP18d (session revocation) closes that.
- **No migration, no ML change, no new dependency, no new permission** (reuses `student:manage`).
- Verified: backend ruff + mypy + **561 passed / 38 skipped** (+5 BP18a: service regenerate-keeps-student +
  tenant-scoped 404; route happy-path + unknown-404 + the login round-trip) + layering; FE lint + tsc +
  `next build` green (`/login` still prerendered static). 2× review loop: **R1** (correctness/security/tenant) —
  no blockers, applied a pre-write-snapshot clarifying comment; **R2** (edges/coverage/a11y) — SHIP, added the
  auth-layer login round-trip proving old-pw-dies/new-pw-works and a suspended-school docstring note.
- **Next:** BP18b (credential-safety guards + self-service + the student name).
