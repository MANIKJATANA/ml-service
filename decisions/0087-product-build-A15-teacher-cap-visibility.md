# 0087 — Product Build A15: Teacher-cap visibility (the BP28 closer)

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review→fix loop clean). **Committed + pushed.**
- **Phase:** **A15** — the optional, cheap closer of **BP28 (Governance & audit completeness)**, Round-4 **R4-A15** /
  Round-3 **R3-A2-04**. **BE + FE — no migration, no ML change, no new dependency, no new permission, no new env var.**

## Context

When a school-admin creates a teacher and the school is at its `max_teachers` cap, they only learned via a
**post-submit 409** (`LimitExceededError` from `OnboardingService.create_teacher`). A15 surfaces the cap on the
school-admin's own staff page **before** they submit — a "N of M teacher seats used" line + a soft-gate on the create
triggers at capacity — while the 409 stays the true server backstop. It closes BP28's stated scope
(R4-A24/25/26 **+ A15**).

**Workflow (owner-directed multi-agent pipeline):** planning agent → plan-review agent → implementation agent →
2× review loop. The planning agent's key find: the dashboard read **already computes both numbers**.

## Decision

### Backend — surface two numbers the dashboard already computed (no new query, no new endpoint)
`DashboardService.school_summary` already loads the school (carrying `max_teachers`) and already computes
`teacher_count = count_by_school_and_role(school_id, Role.TEACHER)` — it merely collapsed the count into a `has_staff`
bool and never exposed `max_teachers`. So A15 just threads both scalars out:
- `services/dashboard_service.py` — `SchoolDashboard` gains `teacher_count: int` + `max_teachers: int`, threaded
  through `_to_dashboard` (**reusing the already-computed `teacher_count`** — no second query; `max_teachers` from the
  already-loaded school row). A one-line comment notes the count is **status-agnostic** (counts active + disabled
  teachers) so it matches the 409's enforcement — a future reader won't "fix" it to active-only.
- `api/schemas/dashboard.py` — a nested `StaffSummary { teacher_count, max_teachers }` block on `DashboardResponse`
  (mirroring the existing `students`/`events`/`media` blocks), always populated by `from_dashboard`.
- **No router change** — `GET /v1/dashboard` is already tenant-scoped (`tenant_of(actor)`) + gated `dashboard:view`
  (which school_admin holds). The surfaced numbers are the **same source the 409 enforces** (`count_by_school_and_role`),
  so display and enforcement can never drift.

### Frontend — a seat-usage line + a soft-gate (advisory-only)
- `lib/api/types.ts` — `staff: { teacher_count; max_teachers }` on `DashboardResponse` (**non-optional**, matching the
  sibling blocks; `from_dashboard` always populates it).
- `app/(school)/staff/page.tsx` — `StaffContent` calls `useDashboard()` (shared `"dashboard"` SWR key → no extra
  request if the nav/dashboard already fetched it), computes `remaining = max_teachers − teacher_count` /
  `atCapacity = remaining <= 0`, and renders a seat-usage line **as its own element** (NOT folded into the
  `PageHeader` description, whose `${total} teachers` is the search-filtered `count_page_by_role` — a search would
  corrupt it): `"{teacher_count} of {max_teachers} teacher seats used"`, prefixed "At capacity — " (remaining == 0) /
  "Over capacity — " (teacher_count > max_teachers, since a cap can be lowered below the count); never a negative
  number.
- **Soft-gate:** at capacity, the "Add teacher" button, the empty-state Add, and the `BulkInviteDialog` "Import CSV"
  trigger are `disabled` with a visible inline note ("You've used all {N} teacher seats. Ask your platform
  administrator to raise the cap." — accurate: the cap is platform-only, BP18c). The disabled reason is conveyed by
  the visible note (not color alone); a genuinely-`disabled` button already announces its state to a screen reader.
- **Advisory-only guard:** if the dashboard read is loading/errored (`dashboard?.staff` absent), the seat line is
  hidden and **nothing is disabled** — the page falls back to today's behavior with the 409 as backstop. A failed
  advisory read can never block a legitimate create.

## Correctness invariants (verified — R1 SHIP)

- **Display == enforcement:** the surfaced `teacher_count`/`max_teachers` are the exact `count_by_school_and_role` +
  `school.max_teachers` values `create_teacher` checks; no second query, no double-count.
- **Tenant-scoped:** `school_id` from the token; a second school's admin sees only their own numbers (proven by the
  new route + service tests, not just presence).
- **The seat line is independent of the search-filtered page total** — sourced from `dashboard.staff.teacher_count`
  (school-wide, authoritative), so a search can't corrupt it and the two numbers can legitimately differ.
- **Fail-safe:** a failed/loading dashboard read disables nothing (409 backstop); the off-by-one is right
  (`remaining == 1` keeps the last create enabled; only `<= 0` gates).

## Files changed (7 — no new files)
Backend: `services/dashboard_service.py` · `api/schemas/dashboard.py` + tests (`test_dashboard_service.py`,
`test_dashboard_routes.py`). Frontend: `lib/api/types.ts` · `app/(school)/staff/page.tsx` ·
`components/staff/bulk-invite-dialog.tsx` (the `disabled` prop for its own trigger).

## Verification

- **Backend:** ruff + mypy clean (176 files) · **pytest 707 passed / 48 skipped** · layering clean. New tests: the
  seat usage reflects the cap + count (incl. a **disabled teacher still consuming a seat** — the status-agnostic
  invariant) and excludes admins; the count is tenant-scoped (a foreign-school teacher doesn't inflate it); the route
  returns the `staff` block and is tenant-isolated. No new gated Postgres test — `count_by_school_and_role`'s
  tenant-scoping is already covered in `tests/adapters/test_postgres_repos.py` (A15 adds no new query).
- **Frontend:** lint + tsc + `next build` clean; `/staff` + `/dashboard` stay `○` (static).
- **2× review→fix loop:**
  - **R1 (correctness): SHIP, 0 blockers.** Verified display==enforcement (no second query), proven tenant isolation,
    the fail-safe advisory guard, the seat-line/search-total independence, and the soft-gate being a real functional
    block. Two NITs (the `role="status"` re-announce; no positive disabled-teacher test) → both handled in R2.
  - **R2 (edge/a11y/copy): SHIP, 0 blockers → 2 fixes + 1 test, all applied:** dropped `role="status"` on the seat
    line (persistent info, not a live region — was re-announcing on every ~60s SWR revalidate), removed the **dead
    `title` tooltip** on the disabled triggers (a `disabled` button is `pointer-events-none` so the tooltip never
    showed — the visible note is the real explanation; also dropped the redundant `aria-disabled`), and added the
    disabled-teacher-counts test.

## Honest limits (documented)

- The seat count is **authoritative** (same source as the 409); the at-capacity **soft-gate is advisory** — the
  server `LimitExceededError`→409 remains the true gate, so a stale client (dashboard SWR is up to ~60s stale +
  revalidates on focus) that attempts a create still correctly gets the 409. Intended defense-in-depth.
- Lowering `max_teachers` below the current count shows "Over capacity" and disables new creates but does **not**
  force-remove any teacher (matches BP18c `update_school`'s documented behavior — surfacing, not enforcement change).
- No FE test harness in this repo (consistent with prior slices) — the FE change is covered by the gate + manual walk.

## Next

**BP28 (Governance & audit completeness) is now fully closed (28a + 28b + A15).** Next Round-4 tier: **BP29
(Teacher-role coherence)** — the second persona finished (role-aware onboarding, delegation-clarity banner + "mine"
marking, a read-only class roster for delegated teachers, an optional "My work" lens, graceful RoleGate denial;
mostly FE, no migration/ML) — through the full Plan → plan-review → implement → 2× review pipeline, committed + pushed
on completion (autonomous). Then **BP30** review-loop power tools · **BP31** onboarding/copy polish.
