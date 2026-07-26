# 0060 — Product Build BP11c: Teacher delegation

**Date:** 2026-07-26
**Status:** Accepted

## Context

BP11 (organizing structure) was sliced into three approve-before-commit sub-phases. **BP11a
(student classes)** ([0058](0058-product-build-BP11a-student-classes.md)) and **BP11b (event
term/category + calendar)** ([0059](0059-product-build-BP11b-event-categories-calendar.md)) landed.
**BP11c** is the last slice and the delegation half: today every teacher sees the whole school —
all ~800 students and ~120 events — with no notion of "my classes". BP11c lets a school admin
**assign teachers to classes** (the BP11a `student_groups`) and **scopes a teacher's list views** to
those classes. BP11b explicitly **deferred the event↔class link to here**.

Per the owner-approved plan (an HTML explainer + a decisions Q&A, 2026-07-26), the three forks were
answered: **scope = students + events** (add the event↔class link), **assign UI = both surfaces**
(class-detail + staff-row), and — the key call — **strictness = focus filter only** (a soft "My
classes / All" default; **no** hard "restrict" boundary, no `users` flag). Cohort-scoped *matching*
stays **BP15**; no ML change.

## Decision (BP11c)

Add a tenant-owned **teacher ↔ class** many-to-many link + an optional **event ↔ class** tag, and a
teacher list **"focus"** scope. Delegation is **convenience-only** — it never widens or narrows what a
teacher can already reach (a teacher could already see the whole school); it only changes the
*default view*. So BP11c introduces **no new security boundary** and needs **no new permission**.

### Data model — migration `0015` (backend chain, `alembic_version_backend`)

- **`teacher_classes`** — a teacher↔class link: `id`, `school_id`→schools CASCADE,
  `teacher_user_id`→users **CASCADE**, `student_group_id`→student_groups **CASCADE**, `created_at`;
  `UNIQUE(teacher_user_id, student_group_id)` (the assignment key). Both CASCADEs mean deleting a
  teacher **or** a class drops the link — never the other side. Indexes both directions
  (`ix_teacher_classes_teacher (school_id, teacher_user_id)` /
  `ix_teacher_classes_group (school_id, student_group_id)`).
- **`events.student_group_id`** — nullable FK → `student_groups`, **ON DELETE SET NULL** (deleting a
  class un-tags its events, never deletes them) — exactly BP11b's `events.category_id`. Index
  `ix_events_school_group (school_id, student_group_id, event_date, id)`. `Event` gains
  `student_group_id`/`student_group_name` (the name **denormalized** via a LEFT JOIN on the object
  reads, like `category_name`).
- Additive only; no existing column changed, no ML chain. Verified up→down→up on a **throwaway**
  Postgres (`bp11c_migtest`, dropped; dev `app` untouched).

### Backend

- **`TeacherClassRepository`** port + `PostgresTeacherClassRepository`: `add` (idempotent — `ON
  CONFLICT DO NOTHING`), `remove` (bool → 404), `replace_for_teacher` (delete-all-then-insert in one
  transaction, dedupes ids), `list_group_ids_for_teacher` / `list_teacher_ids_for_group` — every
  method `school_id`-scoped.
- **`DelegationService`** (pure orchestration over the link + group + user repos): the class-detail
  side (`list_class_teachers` / `assign_teachers` / `remove_class_teacher`), the staff side
  (`list_teacher_classes` / `set_teacher_classes`), and the caller's own focus (`my_classes` /
  `my_group_ids`). Every write validates the class **and** the target is in-school + `role=teacher`
  first — a foreign class/teacher → **404** (never leaks existence, mirrors `_require_managed_user`);
  `assign_teachers` **silently skips** a foreign/non-teacher id (never a cross-tenant link);
  `set_teacher_classes` skips a foreign class id. The teacher/class rosters are composed from the
  existing bounded `list_by_school_and_role` / `list_by_school` reads (no new batch method).
- **The focus scope.** `EventRepository`/`StudentRepository` reads gain `scope_group_ids`
  (threaded through both the row-native and count-sort id-scan paths, the BP9 pattern). Students:
  `student_group_id IN scope` (an **un-classed** student is in no teacher's scope; an empty scope →
  `false()` — no rows). Events: `student_group_id IN scope **OR IS NULL**` (a focused teacher's
  classes' events **plus** untagged/school-wide events; an empty scope → only the untagged). The
  empty-list case is handled explicitly (`false()` / `is_(None)`), never `.in_([])`. Events also gain
  a single `student_group_id` filter (the FE class dropdown), malformed → `false()` like `category_id`.
- **`EventService`** create/update thread `student_group_id` + `_validate_group` (foreign class →
  404); the class follows the event-update **`None` = leave unchanged** convention — it **can't be
  cleared** via PATCH (consistent with category/term/description, [0027](0027-events-media-enqueue-status.md)).
- Routes (tenant strictly from the token): `GET/POST /v1/classes/{id}/teachers`,
  `DELETE /v1/classes/{id}/teachers/{tid}`, `GET/PUT /v1/staff/{id}/classes` — all **`class:manage`**
  (admin-only, reusing BP11a's perm, **no new permission**); `GET /v1/classes/mine` (a teacher's own,
  on `student:manage`, registered **before** `/{group_id}` so the literal wins); `GET /v1/students` &
  `GET /v1/events` gain `mine=true` (+ events `student_group_id`). A shared
  `resolve_focus_group_ids(container, actor, mine)` dep returns the teacher's class ids only when the
  caller is a **teacher** who asked for `mine` — an admin's `mine` is **ignored** (they see all).

### Frontend

- A shared **`FocusToggle`** ("My classes" / "All", `role="group"` + `aria-pressed`) on the students
  + events lists, shown only for a **teacher with ≥1 assigned class** (`canFocus`); default focus ON.
  `focusOn = canFocus && focus` drives `mine=true`; when a teacher has no classes the toggle is
  hidden and `mine` is never sent (they see all — never an empty list). `useMyClasses(enabled)` gates
  its fetch off for non-teachers.
- **Class detail** (`RoleGate` school_admin): a **Teachers** section — a card of teacher chips with a
  remove **X** + an **Assign teachers** dialog (an inline searchable list over the staff roster, the
  BP11a "inline, not portaled popover" pattern).
- **Staff page**: a **Classes** column (per-row `staff-classes:{id}` SWR summary) + an **Edit
  classes** dialog (a checkbox set of the school's classes, initialized from the teacher's current
  assignments, PUT as one set).
- **Events**: an optional class `<select>` on the create/edit dialogs (default "School-wide"; the
  edit omits the no-op "School-wide" option once tagged — can't-clear, like category) + a class
  filter (derived-not-effect stale guard) + the class shown on the list row (with term) and the
  detail `<dl>`; the month calendar threads the class filter + focus through `useMonthEvents`.

## Why

- **Focus, not lockdown** (the owner's call). A soft default keeps the product forgiving — a teacher
  can always view all — and makes the phase the **cheapest, safest** BP11 slice: no `users` column,
  no server-enforced wall, and **no way for `mine` to escalate** (an admin's `mine` is ignored; a
  non-teacher is never scoped). The optional hard "restrict" is a documented future add.
- **A join table, not a pointer.** Unlike one-class-per-student (BP11a), a teacher genuinely manages
  several classes and a class several teachers — a plain N:M with a `UNIQUE` upsert key.
- **`class:manage`, no new permission.** Assigning teachers to classes is the same
  structural/admin act as class lifecycle — reuse BP11a's admin-only perm.
- **Reuse the BP9 list machinery + BP11b's event patterns.** The focus scope is one more WHERE
  clause per list, threaded through the same two paths; the event↔class link copies the
  `category_id` LEFT-JOIN + SET-NULL + can't-clear machinery verbatim.
- **The events "OR untagged" asymmetry is intentional.** A school-wide event (assembly) concerns
  everyone including a teacher's kids, so a focused teacher sees it; an un-classed *student* is no
  teacher's student, so students don't get the "OR NULL".

## Security

- **Tenant isolation by construction.** Every link row + read/write is `school_id`-scoped from the
  token; a class/teacher on create/assign is validated in-school (**404**, never a cross-tenant
  link); the focus scope ANDs under the school scope. No cross-seam ML join (classes are pure
  backend rows).
- **`class:manage` (admin-only)** gates all teacher↔class assignment (a teacher/student → 403); the
  FE assign surfaces are `RoleGate` school_admin. Reads (`/mine`, `mine=true`) ride on the existing
  `student:manage`/`event:manage` (both roles).
- **404 not 403** for a foreign class/teacher — consistent with `_require_managed_user`, never leaks
  existence. `assign_teachers`/`set_teacher_classes` silently skip a foreign id (never a
  cross-tenant write).
- **No privilege change.** Delegation adds no capability — a focused teacher sees a *subset by
  default* of what they could already reach; toggling to "All" restores the prior behaviour exactly.

## Alternatives considered

- **A hard per-teacher "restrict" flag** (the staged plan's opt-in switch). Deferred on the owner's
  call — focus-only is the simpler, safer v1; the flag (a `users` column + server enforcement) is a
  documented future add.
- **Students-only delegation** (defer the event↔class link again). Rejected — the link was already
  parked here in BP11b, and it copies existing machinery; scoping only students would leave a
  focused teacher still swamped by 120 events.
- **A per-IP/per-teacher batch endpoint for the roster.** Not needed — teacher/class rosters are
  bounded per school; composing from the existing `list_by_school*` reads avoids a new repo method.
- **A stored "primary teacher" on the class.** Rejected — N:M is the real relationship (co-teachers,
  a teacher across grades); a pointer would under-model it.

## Consequences

- **No ML change, no new backend dependency, no new env var, no new permission.** One migration
  (`0015`).
- **Honest limits (documented):** focus is a **convenience default, not a boundary** (a teacher can
  always view all; the hard restrict is deferred); an event belongs to **at most one** class
  (multi-tag deferred, mirroring one-class-per-student); the class/term can't be **cleared** via
  PATCH (only changed — the 0027 convention); the staff "Classes" column does **one small SWR per
  visible row** (bounded roster); the class dropdown on a teacher's list shows **all** classes (a
  focused teacher picking a class outside their scope sees nothing — the scope ANDs); cohort-scoped
  *matching* stays **BP15**. **BP11 (organizing structure) is now complete (a, b, c).**
- **Verification:** BE ruff + mypy + **534 passed / 35 skipped** + layering; `test_bp11c_delegation.py`
  (24: the service — assign/idempotent/skip-foreign/remove-404/list/set/replace/my-classes; the
  routes — assign/list/remove, staff set/list, `/mine`, the students & events focus scope [incl. the
  untagged-events rule + the no-classes edge], admin-`mine`-ignored, the event class tag/filter +
  foreign-404, class-delete-un-tags-events, tenant 404s, auth) + a **gated real-Postgres** round-trip
  (`test_teacher_class_links_and_event_group_scope_and_cascade`: the link both-directions/idempotent/
  remove/replace + the event LEFT-JOIN name + the class filter + the focus scope [`IN` OR untagged +
  empty] + **both cascades** [class-delete → events SET NULL + links CASCADE; teacher-delete → links
  CASCADE]) on a throwaway DB; migration `0015` up→down→up on the throwaway. FE tsc + lint + `next
  build` green. 2× review→fix loop, gate green after each. No commit / push without an explicit
  request.
