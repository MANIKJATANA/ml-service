# 0044 — Product Build BP7a: First-run setup checklist

**Date:** 2026-07-15
**Status:** Accepted

## Context

The roadmap's **BP7 (Onboarding & bulk)** bundles four fairly independent capabilities. Grounded in the code (three
exploration passes over the staff-lifecycle, student/enrollment, and dashboard flows), I sliced it into four reviewable
sub-phases, each its own approve-before-commit slice:

- **BP7a — Setup checklist** (this doc) · FE + query-only BE · no migration · no ML.
- **BP7b — Reference-photo quality feedback** · the ML enroll response already carries a per-photo `detail`
  (`no_face`/`multiple_faces`/error) that the backend parses then **discards**; capture it → nullable
  `enrollment_failure_reason` (1-col migration) → expose → FE. No ML change.
- **BP7c — Staff lifecycle + invite model** · server-generated temp passwords shown-once + disable/enable
  (`users.status` already exists, no migration) + resend-invite.
- **BP7d — CSV bulk student import** (the flagship) · nullable `reference_photo_path` migration (name+email →
  pending, photo later) + server-generated student temp passwords + a bulk endpoint looping the reusable
  `create_student` + an add-photo-later flow.

Owner picked the **recommended order — checklist first** (cheapest, high P4/T8, FE-mostly). Source lens: **T8/P4/X4**;
per-view target: `/dashboard` "first-run checklist for a fresh account."

## Decisions

### 1. A server-composed `setup_checklist` on `GET /v1/dashboard` — 5 booleans, only 2 signals net-new
The BP1 dashboard already exposes enough for **3 of the 5** steps (`has_enrolled_student` = `students.enrolled > 0`,
`has_event` = `events.total > 0`, `has_media` = `media.total > 0`). Two are new:
- **`has_staff`** — `UserRepository.count_by_school_and_role(school_id, Role.TEACHER) >= 1` (the method already
  existed; `DashboardService` just gained the `users` dep). A **school-admin does not tick it** — the step is "add a
  *teacher*."
- **`has_distributed`** — a new `EventRepository.count_distributed(school_id)` aggregate whose predicate **mirrors
  BP4's event-level "announced"** (decisions/0041): `notified_at IS NOT NULL OR (auto_notify AND completed_at IS NOT
  NULL)`. One indexed, tenant-scoped scan; **status-agnostic** (an archived event that was distributed still counts as
  "you've distributed once").

The 5 booleans are composed in the **schema layer** (`SetupChecklist` on `DashboardResponse`) so "done" means the same
thing everywhere — notably `has_enrolled_student` keys off *enrolled* (a merely-added, still-pending/failed student does
**not** tick it). **No migration, no ML change** — pure reads.

### 2. The FE checklist retires on distribution, not on all-steps-done
`frontend/app/(school)/dashboard/page.tsx` gains a `SetupChecklistCard` shown while **`!has_distributed`**. Distribution
is the product's whole point (X1) — once a school has distributed, it has reached the core loop and the training-wheels
card retires, **regardless of whether it added a teacher**. A `DashboardBody` orders the two layers: the checklist
(while not distributed) above the command center (stats + alerts, shown once there's any data — a brand-new school sees
only the checklist, since all-zero stat cards are noise). This **replaces the old `FirstRun` invitation** entirely (the
0/5 checklist *is* the better fresh-school guidance).

### 3. The four core steps are the critical path; "add a teacher" is optional
Steps, in order: **enroll a student → create an event → upload photos → distribute → add a teacher**. The first four are
the critical path; **adding a teacher is optional** (a solo school-admin never needs one), so it sits **last**, is
**not counted** in the "N of 4" progress, carries an "Optional" tag, and **never takes the primary CTA** (the first
incomplete *core* step does). This is a deliberate deviation from the roadmap's "add staff → …" ordering — the teacher
isn't on the path to first value. CTAs match each destination page's own button wording (D6): "Add student" / "New
event" / "Add teacher".

## Honest limits (documented, not bugs)

- **Checklist ↔ "ready to distribute" alert overlap.** A school that uploaded+processed but hasn't distributed sees
  both the checklist's "Distribute to students" step and the command center's "N events ready to distribute" alert —
  two prompts toward the same action. Deliberate, reinforcing; not contradictory.
- **"Never hides" if `auto_notify` is off everywhere and Notify is never pressed.** `has_distributed` then stays
  false and the card persists — which is *correct* (the school genuinely hasn't delivered any photos, the X1 gap). In
  practice `auto_notify` **server-defaults true**, so any completed event auto-announces and the card retires on the
  first processed event.

## Verification

- BE gate green: ruff + mypy + **full backend suite 308 passed / 20 skipped** (17 in `test_dashboard_*`). New:
  service tests (has_staff excludes admins; has_distributed via manual notify AND via `auto_notify`+`completed`; the
  all-steps-complete retire state; tenant scoping), a gated real-Postgres `count_distributed` adapter test (manual +
  auto paths, archived-still-counts, exclusions, malformed-id, cross-tenant), and route assertions of the full
  `setup_checklist` block for a mid-setup and a fresh school.
- FE gate green: `tsc --noEmit` + `eslint` + `next build`.
- **2× review→fix loop** (two agents, distinct focus). **R1 (correctness): no blockers, no bugs** — `count_distributed`
  SQL/tenant/predicate verified against BP4; all awaits + all three `DashboardService` construction sites updated;
  `findIndex`/`nextKey` safe; imports clean. **R2 (edge/quality/a11y/copy)** fixed: the missing decision doc (this
  file), a CTA/label inconsistency (D6), completed-label contrast (`text-ink-muted` → `text-ink-secondary`, the repo's
  own sub-AA floor, D8), the primary CTA landing on the *optional* teacher step (→ reordered last + "Optional" tag +
  core-only progress/target), and an added all-steps-complete test. Confirmed non-issue: a teacher viewing the
  dashboard can't hit a 403 dead-end (if a teacher is viewing, `has_staff` is already true → that step shows done, no
  CTA).

## Follow-ups

**BP7b–BP7d** (per this doc's Context + `product/03`): quality feedback, staff lifecycle + invite model, CSV bulk
import — in that order.
