# 0066 — Product Build BP18b: Credential-safety guards, self-service & the student name

- **Date:** 2026-08-06
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the second slice of **BP18 (Account recovery & credential safety)** — the credential-safety net
  around BP18a's student recovery ([decisions/0065](0065-product-build-BP18a-student-credential-recovery.md)).
  Closes the surrounding Round-3 theme-J gaps: shown-once dialogs with no guard, resend-as-silent-reset, the
  unreachable change-password link, the invisible student name, and the untelegraphed last-admin lockout.

## Context

BP18a gave students a recovery path; BP18b hardens the credential surfaces so the path is actually safe to use
and the everyday moments don't quietly lose a one-time password or lock a school out. Everything reuses existing
machinery — **no migration.**

## Decision

Four independent pieces:

1. **Student name on `/auth/me`.** An additive `name: str | None` on `UserResponse` (defaults null on every
   other read — list/roster/provisioned callers unchanged). The `/me` route resolves it for a `student` user via
   the already-wired `container.student_repo().get_by_user_id(school_id, user.id)` (tenant-safe — both args from
   the caller's own token; a missing profile or a staff/platform account → null, never a 500). The shell footer
   shows the name as the primary line for a student, email demoted; staff/platform are unchanged (email primary).

2. **Last-active-admin guard.** `OnboardingService.set_staff_status` refuses to disable a school's only **active**
   admin — a new `UserRepository.count_active_by_school_and_role` (port + Postgres adapter + fake) counts
   active admins; the guard fires only for `role=SCHOOL_ADMIN` + `status→disabled` + a currently-active target +
   `count ≤ 1`, after the idempotent no-op check. It never blocks enabling or teacher disables, and correctly
   catches the "1 active + 1 already-disabled" case (`ValidationError`→400). The FE surfaces the 400 as an error
   toast rather than pre-disabling the button (an R2 a11y call — a `title`-only disabled button isn't
   keyboard/SR-reachable, and the BE guard is authoritative + catches cases a client-side count would miss).

3. **Shown-once close-guards.** The `InviteResultDialog` (copied?) and the bulk-import results dialog
   (downloaded?) route every close path (Esc / overlay / X / Done) through a guard that pops a `ConfirmDialog`
   ("Close without copying/downloading?") when the one-time credential hasn't been secured — so a stray dismissal
   can't strand an admin into the (post-BP18a: per-user resend; pre-BP18a: destructive) recovery path.

4. **Resend-invite confirm.** Staff + admin resend now confirms first when the target is already signed in
   (`status==="active" && !must_change_password`) — resend replaces a working password, so a deliberate
   confirmation guards the common misclick; an awaiting-sign-in / disabled account still resends freely.

Plus: a reachable **"Change password"** `Link` in the shell footer (the page already worked voluntarily).

## Why

- **Additive `name`, not a new endpoint:** the shell already fetches `/auth/me`; one optional field + a scoped
  student lookup avoids a second round-trip and keeps every other `from_user` caller untouched.
- **BE guard as the authority, FE toast over a pre-block:** the R2 review flagged that a disabled button whose
  reason lives in a `title` is invisible to keyboard/SR users, and that a client-side admin count (total, incl.
  disabled) diverges from the correct active-only count. Letting the BE refuse and the toast explain is simpler,
  accessible, and correct for the "1 active + 1 disabled" edge.
- **Guard-all-close-paths:** Radix routes Esc/overlay/X and the explicit Done through the same `onOpenChange`, so
  a single `requestClose`/`handleOpenChange` seam catches every way a credential could be lost.

## Consequences

- No migration, no ML change, no new dependency, no new permission.
- One behavior change: disabling a school's sole active admin now 400s (was allowed). A pre-existing route test
  was updated to add a second admin so its disable-and-reinvite flow still exercises.
- Verified: backend ruff + mypy + **568 passed / 38 skipped** (+7 BP18b: 5 last-admin service tests, a route-level
  sole-admin→400, and a `/me`-name e2e proving student→name / admin→null over HTTP) + layering; FE lint + tsc +
  `next build` green. 2× review loop: **R1** (correctness/security/tenant) — SHIP, no blockers (the `/me` lookup
  is tenant-safe, the guard has no lockout/wrong-block path, the close-guards can't strand a credential or
  deadlock); **R2** (edges/coverage/a11y) — SHIP → added the route-level 400 test and simplified the last-admin FE
  to the BE-guard-+-toast pattern (a11y + removes the total-vs-active divergence).
- **Next:** BP18c (school-record lifecycle — `PATCH /v1/schools/{id}` rename / max_teachers / suspend).
