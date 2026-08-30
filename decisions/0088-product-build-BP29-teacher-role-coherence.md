# 0088 — Product Build BP29: Teacher-role coherence

- **Date:** 2026-08-30
- **Status:** implemented (FE gate green; 2× review→fix loop clean). **Committed + pushed.**
- **Phase:** **BP29** — the second Tier-1 phase of the Round-4 roadmap ([`product/09`](../product/09-improvement-roadmap-round-4.md)),
  **the teacher persona finished**. Closes Round-4 **R4-T01–T08**. **FE-only — no backend change, no migration, no ML
  change, no new dependency, no new permission, no new env var.**

## Context

The teacher is a capable daily-driver, but the role read as half-built: an **un-delegated** teacher saw the whole
school with no explanation (R4-T01 / Round-3 R3-A3-04), the setup checklist dead-ended a teacher on admin-only steps
(R4-T02/T08), a delegated teacher had no read-only view of their class roster (R4-T03), the class dropdown didn't
mark "mine" and the focus scope went stale (R4-T05/T06), and a `RoleGate` denial was a silent bounce (R4-T07). BP29
makes the role **legible** — a banner, a marker, a label, a graceful message, a read-only view of data the teacher
can already fetch.

**Security invariant (unchanged, load-bearing):** delegation stays **convenience-scope, NOT a security boundary**
(BP11c's owner call — a teacher could already see the whole school; `resolve_focus_group_ids` only *narrows the
default view* when a teacher passes `mine=true`, an admin's `mine` is ignored). **BP29 adds NO new boundary** — every
change is legibility over existing `student:manage`/`dashboard:view` reads. No `class:manage` grant to teachers.

**Workflow (owner-directed multi-agent pipeline):** planning agent → plan-review agent (made the item-5 call, confirmed
the item-7 deferral) → implementation agent → 2× review loop.

## Decision — 6 FE-only items

1. **Role-aware onboarding (R4-T02/T08)** — `dashboard/page.tsx`: a teacher no longer sees the admin
   `SetupChecklistCard` (whose "Add a teacher" step is a hard dead-end — `/staff` is `RoleGate school_admin`);
   instead a one-line muted "your role" note. The `school_admin` path + the independent `DashboardContent`
   (stats/alerts) are byte-for-byte unchanged.
2. **Delegation-clarity banner (R4-T01)** — a new `components/delegation/delegation-banner.tsx`, shown when
   `role === "teacher" && !useMyClasses().isLoading && myClasses.length === 0` ("You're seeing all classes. Ask your
   admin to assign you classes to focus your lists."), mounted below the `PageHeader` on the students + events pages
   (renders in every list state incl. empty). Dismissal persisted in `localStorage`
   (`bp29-delegation-banner-dismissed`) via **`useSyncExternalStore`** (server snapshot `false` = shown → SSR-safe, no
   hydration mismatch; a same-tab event re-reads on dismiss — the repo's `use-online-status.ts` pattern). The
   `role === "teacher"` guard is **load-bearing**: an admin's `useMyClasses` is `enabled`-gated off → also returns
   `[]`, so guarding on `length === 0` alone would wrongly show the banner to admins.
3. **Mark "mine" in the class dropdown (R4-T05)** — the class **filter** `<select>` on students + events appends
   " (my class)" to options whose id is in the teacher's `myClasses` set (a text suffix — options can't hold rich
   markup; reads "Grade 5 (my class)" to a screen reader). Only the filter selects (not the admin-leaning
   create/bulk-assign selects).
4. **Live my-classes refresh (R4-T06)** — `use-my-classes.ts` adds `{ revalidateOnFocus: true, refreshInterval:
   60_000 }` (mirrors the BP20 `useDashboard` pattern, overriding the global `revalidateOnFocus: false`), so a
   mid-session delegation change refreshes the banner/markers/scope. Stays teacher-`enabled`-gated → no admin/student
   polling.
5. **Read-only class roster (R4-T03) — baseline, no new surface.** The students-page class filter (now marked "(my
   class)") **is** the teacher's read-only roster path — selecting a class scopes the list to that class's students
   (a read a teacher already can do via `GET /v1/students?student_group_id=`). No dedicated route / no teacher Classes
   nav item (that would be net-new navigation scaffolding for a view the filter already delivers, and risks drift
   toward the mutation-dense admin class-detail page). The admin `classes/[classId]` page stays `RoleGate
   school_admin`.
6. **Graceful RoleGate denial (R4-T07)** — `role-gate.tsx`: the denied branch renders an `EmptyState` ("Not available
   for your role" + a "Go to dashboard" link to `homePathForRole(user.role)`) instead of the silent `router.replace`
   bounce. It still `return`s **before** rendering `children`, so a guarded page's data fetch never fires (the
   doc-comment guarantee preserved). Loading + allowed paths unchanged; `AuthGuard` untouched.

## Deferred — Item 7 "My work" lens (R4-T04)

Deferred (documented). "My uploads" + a per-teacher "pending reviews" count need **new backend reads** — there is no
`created_by`/actor filter on the events or media list endpoints, and the dashboard `needs_review` is **school-wide**
(not per-teacher) — and the one FE-only signal ("my events" via `mine=true`) is **empty for exactly the un-delegated
teacher** BP29 most needs to help. Shipping a half-lens would break the phase's FE-only shape and read as *more*
half-built. It's a small future backend task, not part of BP29.

## Correctness / entitlement invariants (verified — R1 SHIP)

- **No security regression:** the diff is 100% under `frontend/`; the banner/marker/roster ride solely on existing
  tenant-scoped reads (`useMyClasses` = `GET /v1/classes/mine`, the class filter). No new permission, no grant change,
  no endpoint, no `class:manage` for teachers.
- **Admin/platform/student never see a teacher-only surface** — the `role === "teacher"` guard precedes the
  `length === 0` check everywhere; platform_admin/student never reach the `(school)` group (AuthGuard).
- **`useSyncExternalStore`** is faithful (stable module-level `subscribe`, primitive-boolean `getSnapshot` → no
  "should be cached" warning, `window`/`localStorage` only touched outside render) — no hydration mismatch, no
  re-subscribe storm.
- **RoleGate** never renders guarded `children` on denial (fetch never fires); the `router.replace`/`useEffect`
  imports were removed (no dangling unused → lint-safe).

## Files changed (6 — 1 new)
`components/delegation/delegation-banner.tsx` (new) · `app/(school)/dashboard/page.tsx` ·
`app/(school)/students/page.tsx` · `app/(school)/events/page.tsx` · `lib/hooks/use-my-classes.ts` ·
`components/role-gate.tsx`.

## Verification

- **Frontend gate:** `npm run lint` + `npx tsc --noEmit` + `next build` all clean; `/dashboard`, `/students`,
  `/events` stay `○` (static) via their Suspense boundaries. **No backend change → no backend suite delta.**
- **No FE test harness** in this repo (the documented norm) — verification is the gate + the manual-walk logic
  (a teacher with 0 classes: "your role" note + banner + no markers; a teacher with ≥1 class: no banner + `FocusToggle`
  + "(my class)" markers + live refresh; an admin: checklist unchanged, no banner, no markers; a denied deep-link:
  the graceful message).
- **2× review→fix loop:**
  - **R1 (correctness/entitlement): SHIP, 0 blockers.** Verified the entitlement safety, the load-bearing role guard,
    `useSyncExternalStore` fidelity, Rules-of-Hooks, the SWR override staying teacher-gated, and the RoleGate
    fetch-never-fires guarantee. Two NITs (cosmetic import order; a one-frame checklist flash while `useMe` resolves)
    — both correctly not worth acting on.
  - **R2 (edge/a11y/copy): SHIP, 0 required fixes → 1 NIT applied:** the RoleGate denial `EmptyState` moved
    `role="alert"` → `role="status"` (an informational access-denied screen, not an error/data-failure — the app
    convention, per 0037, reserves `role="alert"` for failures). The other 3 NITs were "leave as-is" (the
    dismissed-flag being permanent-per-browser across re-delegation is acceptable for a low-urgency nudge; the two
    inline marker `Set`s are the low-ceremony choice; the "Go to dashboard" copy holds because RoleGate only wraps
    `(school)` pages where the sole deniable role lands on `/dashboard`). Confirmed: the banner is `role="status"`
    (not `alert`), the dismiss is a real `<button aria-label="Dismiss">` with a focus ring, and no existing
    `Callout`/`Banner` primitive exists to reuse (the ~30-line hand-roll is justified).

## Honest limits (documented)

- **Legibility, not enforcement** — a teacher still sees the whole school; the banner just explains it. A real
  delegation boundary would be a different phase (BP11c's owner call stands).
- **Banner dismissal is per-browser and permanent** (`localStorage`) — a teacher who dismisses it, gets delegated,
  then is un-delegated again won't see it return (acceptable for a low-urgency nudge; resetting on re-delegation would
  need prior-state tracking, over-engineering for the payoff).
- **Read-only roster is the marked filter**, not a dedicated "open my class" page (a thin future add if teachers ask).
- **The "My work" lens is deferred** (needs backend reads that don't exist).
- **No FE automated tests** (the repo norm) — BP29's FE logic is covered by typecheck + manual walk only.

## Next

**BP29 (Teacher-role coherence) is complete.** Next Round-4 tier: **BP30 (Review-loop power tools at scale)** —
threshold multi-select, discoverable batch-undo + a "show hidden/rejected" filter, an optional table view, add-students
pagination feedback, lightbox auto-paging (FE-only, composes BP13/BP22 primitives; R4-A20/21/22/23, F04). Then **BP31**
(onboarding feedback loop & copy polish). Each through the full Plan → plan-review → implement → 2× review pipeline,
committed + pushed on completion (autonomous).
