# 0068 — Product Build BP18d: Session revocation + student disable

- **Date:** 2026-08-09
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the fourth and final slice of **BP18 (Account recovery & credential safety)** — after BP18a's student
  recovery ([0065](0065-product-build-BP18a-student-credential-recovery.md)), BP18b's safety net
  ([0066](0066-product-build-BP18b-credential-safety.md)), and BP18c's school lifecycle
  ([0067](0067-product-build-BP18c-school-record-lifecycle.md)). Closes the **honest limit BP18a documented** (a
  reset kills the password at login but an already-issued refresh token survives ≤14 days) and adds a
  **non-destructive student kill-switch**. **The one migration of BP18 (`0017`).**

## Context

Two gaps remained after BP18a–c:

1. **Sessions outlived a password change.** BP18a/BP7c resend + `change_password` rewrote the password hash, so the
   old password stopped working *at login* — but any JWT already minted (access ≤15 min, **refresh ≤14 days**) kept
   working until it expired, because nothing tied a token to the current password. A stolen laptop or a
   left-behind session survived the very reset meant to lock it out. There was no "log out everywhere."
2. **A student's only kill-switch was delete** — which BP8e makes destroy their matched-photo history. Staff had
   no way to *pause* a student's access (lost device, left mid-term) without erasing them.

## Decision

### Part A — session revocation ("log out everywhere") · migration `0017`
A per-account **`users.token_version`** counter (`INTEGER NOT NULL DEFAULT 0`, migration `0017`, additive +
reversible). Every JWT carries the issuing user's version as a **`tv`** claim (on **both** the access and refresh
tokens). The backend compares `tv` to the row's `token_version`:

- **On every request** — `get_current_user` (`api/deps.py`) already reloads the user for the disabled-account
  check; it now also rejects a `tv` mismatch → **401**.
- **On refresh** — `AuthService.refresh` rejects a stale `tv` → **401** (so a pre-reset refresh token can no
  longer mint fresh access tokens — the exact BP18a gap).

`UserRepository.set_password` gains `revoke_sessions: bool = True` and **increments `token_version` in the same
UPDATE** as the hash. So BP18a's student resend, BP7c's staff/admin resend, and `change_password` **all** revoke
old tokens automatically — a fresh account starts at 0, nothing to kill.

- **The rehash trap:** `AuthService._maybe_rehash` (transparent argon2 re-hash on login) passes
  `revoke_sessions=False`. If it bumped `token_version`, the login that triggered the rehash would invalidate the
  token it just issued. This is the one caller that must **not** revoke.
- **Self-change stays logged in:** `change_password` bumps `tv` (revoking the caller's *own* tokens too), so it
  **re-issues a fresh pair** with the new `tv` (reloading the user first so issuance uses the bumped version) and
  returns them — the route response changes from **204 → 200 `TokenResponse`**, and the BFF
  (`/api/auth/change-password`) swaps the cookies so the user isn't logged out of their own session mid-change.

### Part B — student disable (non-destructive) · no migration
`StudentService.set_status(school_id, student_id, status)` — a 1:1 shape of `OnboardingService.set_staff_status`:
tenant-scoped `get_student` (a foreign/missing student → **404 before any write**), flips the linked login via the
existing `users.set_status`, returns a **re-read** `Student`. Idempotent (setting the current status skips the
write). **No last-admin-style guard** — a student's status locks out only themselves. Auth already honours a
disabled account at login, refresh, **and** the per-request `get_current_user` reload (0024), so a disabled
student is immediately locked out yet keeps every profile/photo/`match` row (unlike delete).

- Route **`PATCH /v1/students/{student_id}/status`** (`student:manage`, tenant from the token), reusing the
  existing `UpdateUserStatusRequest` (`{status}` → free 422 on a bad value), response `StudentResponse`.
- The **`Student` read model gains `status: UserStatus`** off the *existing* users JOIN
  (`postgres_students.py::_select_with_email_and_class` selects `UserRow.status`; `_to_student` maps it, defaulting
  `active` for a fresh `create()`), denormalized like `email`/`student_group_name`. Surfaced on
  `StudentResponse.status` (inherited by `StudentListItem`).
- **FE:** a `setStudentStatus` endpoint; on the student detail a **"Disable login"** (behind a `ConfirmDialog` —
  it locks the student out) / **"Enable login"** (direct) action + a **"Login: Active/Disabled"** `StatusPill`
  (matching the staff-page tone convention: disabled → neutral "Disabled"); on the students list a compact
  **"Disabled"** pill in the status cell so a locked-out student is visible at a glance.

## Why

- **`token_version` over a token denylist:** a per-user counter is one integer, compared against the already-loaded
  user row — no new store, no TTL bookkeeping, no per-token state. Revocation is a side-effect of the write that
  already happens (`set_password`), so there is nothing extra to remember to call.
- **Disable writes to `users`, reads on the student JOIN:** login status lives on the `users` row (auth's source
  of truth); the student read model reflects it via the JOIN it already runs for `email`. So the disable is a
  single `users.set_status` and the UI sees it on the next student read — no second column, no sync. (The test
  `FakeStudentRepo` mirrors this by resolving status on every read via a `_status_of` link to the fake user repo,
  not snapshotting it at create — the same read-time semantics as the real JOIN.)
- **`change_password` re-issues rather than 204-and-logout:** revoking the caller's own tokens is correct
  ("everywhere" includes here), but logging a user out for changing their own password is hostile — so we hand
  back a fresh pair keyed to the new version.

## Consequences

- **Migration `0017`** (backend chain, `alembic_version_backend`): `users.token_version INTEGER NOT NULL DEFAULT
  0`. Additive, no backfill needed (existing rows adopt 0), fully reversible. **No ML change, no new dependency, no
  new permission** (disable reuses `student:manage`).
- One behaviour change: **`POST /v1/auth/change-password` now returns 200 `TokenResponse`** (was 204). The BFF was
  updated to set the re-issued cookies; no other caller depended on the 204.
- **Honest limits (documented):**
  - `token_version` revocation is keyed on a password *change/reset*. **Disabling a student's login is enforced by
    a different mechanism** — the per-request status reload in `get_current_user` **and** the refresh path's
    status check (which runs *before* `tv`), not by `tv` — so a disabled student's already-issued **access token
    is rejected on the next request and their refresh token is rejected on the next refresh** (no survival gap).
    The two mechanisms are **independent**: `get_current_user` checks status first, then `tv`, so a
    disabled-and-password-changed user is rejected by whichever fires — no interaction bug.
  - A plain admin "log this user out" *without* a password change or a disable is **not** a feature: bumping
    `token_version` requires a password write today. A standalone "sign out everywhere" button is a future
    one-line `token_version`-bump.
- Verified: migration `0017` **up→down→up on a throwaway Postgres** (`bp18d_migtest`, dropped; dev `app` DB
  untouched — the column appears as `integer`, drops, and re-adds cleanly); BE ruff + mypy + **582 passed / 38
  skipped** (+5 unit/route: disable↔enable + idempotent + tenant-404 service tests, a disable→login-401→re-enable
  e2e + an unknown-404 route test) + a **gated real-Postgres** pass (32 passed on the throwaway DB) extended with a
  `token_version` bump-on-change / no-bump-on-rehash round-trip **and** a student-read-model-reflects-login-status
  JOIN round-trip + layering; FE lint + tsc + `next build` green (`/login` stays statically prerendered).
  2× review loop: **R1** (correctness/security/tenant/async) — **SHIP, no blockers** (traced all nine focus areas
  clean: revocation complete on both authenticated paths, the rehash + self-reissue traps both handled, student
  disable 404s before any write, `Student.status` populated on every read path with a faithful fake, the 204→200
  contract consistent through router/BFF/tests); **R2** (edges/coverage/a11y) — **SHIP** → relabelled the list
  pill **"Login disabled"** (so it never reads as an enrollment state), added a **disabled-student's-live-access-
  token → 401** route test (the mid-session kill, not just login-time), and recorded the two honest-limit notes
  above. The detail-page toggle keeps its visible-text accessible name (icons `aria-hidden`), matching R2's call.
- **BP18 (account recovery & credential safety) is now complete (a, b, c, d)** — Round-3 Critical #1 (theme J) is
  fully closed. Next: the owner picks the next Round-3 phase (BP19 pipeline resilience — Critical #2 — is the
  recommended follow-on) and re-confirms scope.
