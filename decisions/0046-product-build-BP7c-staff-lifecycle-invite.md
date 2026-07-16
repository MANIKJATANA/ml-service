# 0046 — Product Build BP7c: Staff lifecycle + invite model

**Date:** 2026-07-16
**Status:** Accepted

## Context

The third BP7 sub-phase (after BP7a checklist / BP7b quality feedback; see
[decisions/0044](0044-product-build-BP7a-setup-checklist.md) for the four-slice split). Today staff/admin accounts are
provisioned with a **caller-typed** temp password that is never returned, there's **no way to disable** a departed
teacher (the `users.status` column exists but nothing writes it), and **no way to re-issue** a lost temp password. Fails
**T5/X4**. BP7c turns provisioning into a proper **invite model** + lifecycle. **Backend + frontend; NO migration** —
`users.status` (active/disabled) already exists and the auth layer already rejects a disabled account.

**Scope calls (stated + owner-visible):** this slice covers **teachers + school admins**. **Students stay
caller-supplied** (their create dialog does the reference-photo upload + a typed password) and move to server-generated
temp passwords in **BP7d** (bulk import needs it anyway). The **"N of M" teacher capacity** already lives on the
platform school-detail (BP2 rollup); the school-admin's own `/staff` shows a teacher **count**.

## Decisions

### 1. Server-generated temp passwords, shown once
`create_teacher` / `create_school_admin` now **generate** the temp password server-side (`secrets.token_urlsafe(12)` — a
CSPRNG, 16 URL-safe chars, over the 8-char policy floor), hash it, set `must_change_password=True`, and return it
**exactly once** wrapped in a new `ProvisionedUser` VO → `ProvisionedUserResponse {user, temp_password}`. `password` is
**dropped** from `CreateUserRequest` (email only). The plaintext is returned only by create + resend — never by
list/get/me (which stay `UserResponse`), never logged, only its hash persisted.

### 2. Disable / enable — no migration
A new `UserRepository.set_status(user_id, status)` (port + Postgres adapter + fake) writes the pre-existing
`users.status`. `OnboardingService.set_staff_status` (idempotent) drives it. Disable is **real, not cosmetic**: the auth
service rejects a non-`active` user at **login**, **refresh**, *and* the per-request `get_current_user` reload — so a
live access token stops working the instant an account is disabled. Routes: `PATCH /v1/staff/{id}` (teacher) and
`PATCH /v1/schools/{school_id}/admins/{id}` (admin), body `{status}`.

### 3. Resend-invite
`OnboardingService.resend_invite` regenerates a distinct temp password, `set_password(..., must_change_password=True)`,
and returns it once. Routes: `POST /v1/staff/{id}/resend-invite` and `POST /v1/schools/{school_id}/admins/{id}/resend-invite`.
Works on a disabled account too (re-invite ≠ re-enable — enabling stays an explicit, separate action).

### 4. One entitlement guard — `_require_managed_user`
Both lifecycle ops funnel through `_require_managed_user(school_id, user_id, role)`: the target must **exist**, belong to
`school_id`, **and** have the expected `role` — else `NotFoundError` (**404, not 403** — never leak that a user of
another school/role exists). This structurally blocks (a) cross-tenant (staff routes take `school_id` from the token,
platform routes from the URL — a platform admin must pass the target's real school), (b) wrong-role (the teacher route
can't touch an admin/student and vice-versa), and (c) **self-action** (the manager is always a strictly different role
than the managed — a school-admin manages teachers, a platform-admin manages school-admins). School-admins can't reach
the platform routes at all (`school:manage`, platform-only).

### 5. Frontend — shown-once + row actions
A shared **`InviteResultDialog`** (used by both the staff page and the platform school detail) shows the one-time temp
password with a **Copy** button (`copyToClipboard`, graceful fallback → toast) and clear "won't be shown again" copy;
the plaintext lives only in component state. Create dialogs drop the password field (email only). Each teacher/admin row
gets **Resend invite** + **Enable/Disable** actions (per-row `aria-label` naming the account, matching the
appearance-editor a11y convention); a resend revalidates the roster so the status pill updates.

## Honest limits (documented)

- **Last active admin lockout is allowed.** A platform admin *can* disable a school's only active admin (leaving it with
  none) — recoverable by the platform (re-enable / add another), so not guarded. Documented, not a bug.
- **Students not yet on the invite model** (→ BP7d); **capacity "of M"** is platform-side only (BP2).

## Verification

- BE gate green: ruff + mypy + **full suite 327 passed / 22 skipped**. New: `test_onboarding_service.py` (server-gen +
  distinct-per-account + idempotent set_status + disable/enable + resend + resend-on-disabled + tenant/role 404 guards),
  `test_onboarding_routes.py` (create returns `{user, temp_password}` with no `password_hash`; **disabled teacher → login
  401 → re-enable → 200** e2e; resend; tenant/role 404s; platform admin disable + wrong-school 404; the list omits
  `temp_password`), and a **gated real-Postgres** `set_status` round-trip (incl. `NotFoundError`). **No migration.**
- FE gate green: `tsc --noEmit` + `eslint` + `next build`.
- **2× review→fix loop** (two agents). **R1 (correctness + SECURITY): no blockers, no should-fix** — the entitlement
  guard (404-not-403, cross-tenant/wrong-role/self-action all blocked), CSPRNG + hash-only persistence + never-logged,
  and the lockout guarantee (login + refresh + per-request reload) are each airtight with matching tests. **R2
  (edge/quality/a11y/coverage)** → applied its one should-fix (per-row `aria-label` on the action buttons) + the R1
  resend-revalidate nit + two regression-guard tests (list omits `temp_password`; resend-on-disabled). Left as noted: the
  `StaffActions`/`AdminActions` duplication (acceptable for two personas).

## Follow-ups

**BP7d** (CSV bulk student import) next — which also moves **students** to server-generated temp passwords and lands the
in-place reference-photo **replace** that completes BP7b's loop. Optional later: a "Reset password" framing distinct from
"Resend invite"; a last-active-admin guard; extracting a shared row-actions component if a third managed persona appears.
