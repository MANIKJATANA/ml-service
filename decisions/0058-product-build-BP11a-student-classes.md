# 0058 — Product Build BP11a: Student classes

**Date:** 2026-07-26
**Status:** Accepted

## Context

BP11 (organizing structure, [`04-improvement-roadmap-round-2.md`](../product/04-improvement-roadmap-round-2.md)
§BP11) is the Round-2 review's highest-leverage *structural* gap (theme B, lenses P3/P5/X5): at Greenfield
scale the whole product is **one flat 800-row students table + one flat 120-row events list**. That single
absence blocks **findability**, **delegation**, and **reporting** at once.

Per the owner-approved plan (an HTML explainer + a decisions Q&A, 2026-07-26), BP11 is sliced into three
approve-before-commit sub-phases — the house style (BP7a–d, BP8a–e):

- **BP11a — student classes** (this doc): a `class`/section concept + student assignment + the class filter.
- **BP11b — event term/category + calendar** (next): labels on events + a calendar view.
- **BP11c — teacher delegation** (last): assign teachers to classes + scope their lists (staged: a "focus"
  filter by default, an opt-in "restrict" switch).

Owner decisions locked for BP11a: **one class per student** (a nullable pointer, not a many-groups join);
cohort-scoped **matching stays out of scope** (BP15) — classes are organizational only, **no ML change**.

## Decision (BP11a)

Add a tenant-owned **class** concept and the machinery to organize students by it. Backend adds **one new
table + one nullable FK + one repo + one service + one router**; the students slice + list gain a class
filter; the FE gets a **Classes** management surface + a class filter/badge/selector.

### Data model — migration `0013` (backend chain, `alembic_version_backend`)

- **`student_groups`** — a class: `id`, `school_id` → `schools` CASCADE, `name` (required), `grade`/`section`
  (nullable labels), timestamps. Index `ix_student_groups_school(school_id, name, id)`. Bounded per school
  (a few dozen), so its list read is **unpaginated**.
- **`students.student_group_id`** — nullable FK → `student_groups` **ON DELETE SET NULL** (deleting a class
  **un-assigns** its students, never deletes them). Index `ix_students_school_group(school_id,
  student_group_id, id)`.
- Additive only; no existing column changed, no ML chain. Verified up→down→up on a **throwaway** Postgres
  (`bp11a_migtest`, dropped; dev `app` untouched).

### Backend

- **`StudentGroupRepository`** port + `PostgresStudentGroupRepository`: tenant-scoped `create`/`get`/
  `list_by_school`/`update` (full-replace of name/grade/section)/`delete` (bool: false = absent/foreign) +
  `student_counts` (one grouped scan over `students.student_group_id`).
- **`StudentRepository`** grows a `student_group_id` filter on `list_page`/`count_page`/`list_ids` (a
  malformed id → `false()`, never an `IS NULL` that would wrongly match un-classed students), a class-name
  **LEFT JOIN** on the object reads (so the read model carries `student_group_name` for display, like
  `email`), and `set_group` (single, clear with `None`) + `set_group_bulk` (tenant-scoped `UPDATE … WHERE
  school_id AND id IN (…)`, a foreign id silently skipped).
- **`ClassService`** (pure orchestration over the two repos): `list_classes` (+ counts), `create/get/update/
  delete_class`, `assign_students` (bulk; validates the class in-school → 404 first), `set_student_group`
  (single; validates both the student and — when set — the target class are in-school → 404, else the
  student is never moved).
- **`class:manage`** — one new permission granted to **school_admin only** (the same one-line admin/teacher
  difference as `audit:view`). Class **lifecycle** (create/edit/delete) needs it; **reads + student
  assignment** ride on the existing `student:manage` (both roles).
- Routes: `GET/POST /v1/classes`, `GET/PATCH/DELETE /v1/classes/{id}`, `POST /v1/classes/{id}/members`
  (bulk assign), and `PATCH /v1/students/{id}` (set/clear one student's class, `student_group_id`
  required-but-nullable so an empty body is a 422, never a silent un-assign) + a `student_group_id` query
  filter on `GET /v1/students`. Tenant strictly from the token.

### Frontend

- A **Classes** nav item (school_admin) + a `(school)/classes` page (`RoleGate` school_admin): list classes
  + member counts, create/rename/delete (one shared `ClassFormDialog`).
- A `classes/[classId]` detail: the roster (the students list filtered to the class) with per-row remove +
  an **Add students** dialog — an **inline** searchable list (not a portaled popover, so the modal
  scroll-lock never blocks it — the BP10 trap) that accumulates picks then bulk-assigns.
- The **students list** gains a class `<select>` filter (from `useClasses`) + a class badge per row; the
  **student detail** gains an inline class `<select>` (assign/change/clear). A `useClasses` SWR hook keyed
  `"classes"` so a create/rename/delete refreshes every surface.

## Why

- **A nullable pointer, not a join table.** "One class per student" matches how a school thinks ("Aisha is
  in Grade 3B") and keeps assignment/filter/grouping a single indexed column. Multi-group membership
  (a homeroom *and* a club) is a documented future extension, not a v1 need.
- **Reuse the BP9 list machinery.** The class filter is one more `_filtered` WHERE clause + one index; the
  count-sort path and pagination are unchanged. No new list plumbing.
- **Denormalize the class name onto the read model** (LEFT JOIN), like `email` — so the list/detail show a
  class without the FE needing the full class list loaded, and a rename shows everywhere on refresh.
- **Split the permission the way the codebase already does.** Structural lifecycle is admin-only
  (`class:manage`); day-to-day roster assignment is both roles (`student:manage`). Adding teacher class
  management later is a one-line `ROLE_PERMISSIONS` edit.
- **SET NULL, not CASCADE, on the class FK.** Deleting a class must never delete students — it un-assigns
  them. This is the safe, reversible default (re-assign to restore).

## Security

- **Tenant isolation preserved by construction.** Every class row has `school_id`; every read/write filters
  it from the token. Assigning a student or a class is validated in-school first (foreign → 404, never a
  cross-tenant move); the bulk `UPDATE` is `WHERE school_id AND id IN (…)`, so a foreign student id is
  silently skipped, never moved.
- **No cross-seam join.** Classes are pure backend rows — the isolated ML `matches` seam is never
  SQL-joined (the standing architecture invariant holds).
- **`class:manage` is admin-only**; a teacher (or student) hitting a lifecycle route is a 403; the FE
  `/classes` page is `RoleGate` school_admin (a teacher deep-link redirects home). Reads + assignment stay
  `student:manage` (both roles) so teachers can filter + organize.
- **404 not 403** for a foreign class/student — consistent with `_require_managed_user`, never leaks
  existence.

## Alternatives considered

- **A many-groups membership join table.** Rejected for v1 — more moving parts (N:M queries, membership
  CRUD) for a need (delegation + findability + reporting) that one class per student fully serves.
  Documented as the future extension when activity groups arrive.
- **Free-text class name only (no grade/section).** Rejected — `grade`/`section` are the axes schools
  filter/report by; keeping them as optional columns is cheap and unlocks the BP11b/analytics slicing.
- **A `GET /v1/classes` per-page/paginated envelope.** Rejected — classes are genuinely bounded per school
  (a few dozen); a plain unpaginated list is simpler and also feeds the FE filter dropdown in one fetch.
- **Class assignment on the create-student / CSV-import path.** Deferred — a class filter + a per-student /
  bulk-assign action covers the v1 need; wiring class into create/import is a small follow-up.
- **A reusable `<Select>` primitive.** Deferred — two native `<select>`s (list filter + detail selector),
  styled to the tokens, is enough; a primitive is worth it once a third consumer appears.

## Consequences

- **No ML change, no new backend dependency, no new env var.** One new permission (`class:manage`), one
  migration (`0013`).
- **Honest limits (documented):** one class per student (multi-group deferred); class isn't yet set at
  create/CSV-import time (filter + assign action instead); the "Add students" dialog is an inline searchable
  list (no arrow-roving, mirroring BP5/BP10 pickers) that bulk-assigns; the FE uses two native `<select>`s
  (no custom primitive); the list rollup counts stay raw ML (BP2 divergence, unchanged). BP11b (event
  labels + calendar) and BP11c (teacher delegation) are the next slices.
- **Verification:** BE ruff + mypy + **480 passed / 33 skipped** + layering; new unit tests
  (`test_bp11a_classes.py`, 23) covering the service (create/list-counts/update/delete-un-assigns, single +
  bulk assign, tenant scope, foreign-class/student 404s) + the routes (the `class:manage` vs `student:manage`
  split, the students class filter, the PATCH set/clear, cross-tenant 404s, auth) + **2 gated real-Postgres**
  round-trips (the class CRUD/counts/LEFT-JOIN/filter/**SET NULL cascade**, and the bulk tenant-scope) on a
  throwaway DB. FE tsc + lint + `next build` green. 2× review→fix loop, gate green after each. No commit /
  push without an explicit request.
