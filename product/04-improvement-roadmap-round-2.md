# 04 — Improvement Roadmap · Round 2 (the experience at scale, BP9–BP17)

> **This file = "what we build next, in what order, and why" for Round 2.** It is the sibling of
> `03-improvement-roadmap.md` (which holds the completed **BP1–BP8** track); this one holds the **BP9–BP17**
> track surfaced by the scale + per-role review in `02-product-review.md`. Same format, same conventions:
> each phase is a reviewable slice with its own `decisions/` record, built **docs-first, on explicit
> approval** (repo convention).
>
> **Prioritization is the product specialist's call** (owner-delegated). **Consent/legal is out of scope**
> (owned by legal via school contracts).
>
> _Snapshot: 2026-07-25. Source: `02-product-review.md` (Greenfield-scale, per-role review). BP1–BP8 live in
> `03`. **Owner sequencing calls (2026-07-25): BP12 (distribution reach), BP15 (accuracy at scale), and
> BP16 (lifecycle & retention) are deprioritised to the back of the queue** — lead with the cheaper,
> higher-urgency phases first; BP12/BP15 are the infra/ML-heavy flagships, BP16 is pure risk-reduction._

---

## 1. The Round-2 thesis

At **Greenfield scale** (~800 students across grades, ~120 events/year, a 3rd-year student with ~900 photos),
the product **can't be turned on (theme A), can't deliver (C), and organizes nothing (B)** — and underneath,
its lists and galleries weren't built to hold that much (D). (Themes are defined in `02` §4; each phase cites
the ones it closes.)

So the sequence **leads with the low-risk substrate — BP9 + its image companion BP17** (pagination/search
fix the queries; thumbnails fix the bytes) — then the **switch-on unblocker (BP10)**, then the **structural**
gap (BP11), then the remaining **M-effort** wins (BP13/BP14) — and **defers three phases to the back** (BP12
distribution, BP15 accuracy, BP16 lifecycle), per the owner's calls. Those stay fully specced so they're
ready to pick up when they come off the queue.

**Effort legend** (from `03` §1): S ≈ ≤1 phase, one surface · M ≈ multi-surface or a small new capability ·
L ≈ net-new across services (+ migration / infra). **Impact:** H/M/L on the product.

---

## 2. Effort × Impact map

| Effort | High impact | Lower impact |
|---|---|---|
| **M** | **BP9** scale-ready lists/galleries · **BP17** image thumbnails/derivatives *(S–M)* · **BP10** bulk enrollment · **BP11** org structure (classes/terms) | **BP13** bulk actions & batch review · **BP14** program analytics & trends · **BP16** lifecycle & retention *(deprioritised → back)* |
| **M–L** | **BP12** distribution reach (email to student account + share) — *deprioritised → back* | **BP15** accuracy at scale (staleness + reconciliation) — *deprioritised → back* |

---

## 3. Build order (recommended)

**BP9 → BP17 → BP10 → BP11 → BP13 → BP14**, then the deprioritised phases **BP12 → BP15 → BP16**.

> The BP numbers are **stable identifiers** (assigned when this track was drafted); the **order below — not
> the number — is the priority.** BP17 (thumbnails) pairs with BP9 as the fast-UI substrate. BP12, BP15, and
> BP16 keep their IDs but sit at the back after the owner's deprioritisation calls.

---

## 4. The phased backlog

### BP9 — Scale-ready lists & galleries · **Effort M · Impact H · FE + query-only BE (indexes = migration)** · ✅ landed ([decisions/0055](../decisions/0055-product-build-BP9-scale-ready-lists-galleries.md))
- **Problem (theme D):** every list and gallery **loads everything** and filters/sorts **client-side**; the
  gallery reads **load the whole school roster / event list into Python** and filter in memory (`02` §5).
  Only `/audit/downloads` paginates. At 800 students / 2000-photo events: slow pages, janky scroll,
  download-all that OOMs. Fails **P5/D8**.
- **Change:** server-side **pagination** (cursor or limit/offset) + **server search/filter/sort** on the
  ~11 unbounded list/gallery endpoints; **refactor `GalleryService`** to fetch only the matched students/
  media in SQL (no full-roster loads); FE **infinite-scroll / virtualization** on lists + galleries;
  **streaming** download-all. Adds a few indexes (a migration).
- **Persona:** every role (Linear+Stripe for admin lists, Pinterest for galleries). **Source lens:** P5, D8, P8.
- **Acceptance:** an 800-student / 120-event / 2000-photo school loads each screen in one bounded page;
  search/sort hit SQL, not the client; no gallery path calls `list_by_school`; download-all survives 900
  photos; gates green. **Why first:** lowest-risk (mostly query-only), fixes felt lag *now* (a photoless CSV
  import already yields 800-row lists), and it's the substrate every later phase's new views ride on.

### BP17 — Image thumbnails & derivatives · **Effort S–M · Impact M–H · BE + FE (+ storage)** · ✅ landed ([decisions/0056](../decisions/0056-product-build-BP17-image-thumbnails.md))
- **Problem (theme D):** **no thumbnails/derivatives exist** — every list and gallery loads **full-res**
  images (`00` §2, §9). A 2000-photo gallery pulls 2000 full-size files; the students list shows no face at
  all (the `StudentAvatar` primitive already ships a wired-but-unused `photoUrl`). This is the other half of
  the scale-lag story — BP9 fixes the queries, BP17 fixes the bytes. Fails **P5/D8/P8/P9**.
- **Change:** generate/serve a **low-res derivative** per image — cheapest path is **Supabase image
  transforms** (`00` §2 flags them as available-but-unwired: a width/quality-parametrised URL), else a stored
  thumbnail minted on upload. Serve thumbnails on **gallery tiles** and **list avatars**, keep full-res for
  the lightbox + download. **Student list:** show the reference photo as a small avatar next to the name —
  **use the compact thumbnail URL when present, fall back to the full-res URL when it's null** (wiring the
  reserved `StudentAvatar.photoUrl`).
- **Persona:** every role (student galleries + admin lists). **Source lens:** P5, D8, P8, P9.
- **Acceptance:** tiles + list avatars load a small derivative (≫ smaller than full-res); a 2000-photo gallery
  scrolls smoothly; the students list shows a face per row (thumbnail-or-full-res fallback); the lightbox +
  download still serve full-res; gates green.

### BP10 — Bulk enrollment (photos at scale) · **Effort M · Impact H · BE + FE · no migration** · ✅ landed ([decisions/0057](../decisions/0057-product-build-BP10-bulk-enrollment.md))
- **Problem (theme A — the switch-on blocker):** CSV import (BP7d) creates students **photoless → pending**;
  the only way to attach a face is BP7d-2's **one-at-a-time** "Add photo". 800 students = 800 manual uploads.
  **The product can't be turned on at scale.** Fails **X4/T8/P5** — the review's highest-severity finding.
- **Change:** **filename-mapped bulk reference-photo upload** — a multi-file / zip drop where `email.jpg` or
  `student_id.jpg` maps to the student → loop the existing `set_reference_photo` + `_run_enroll` (BP7d-2);
  a **bulk re-enroll** for `failed`/`pending`. Reuses existing ports (signed upload URL, `ObjectStore`,
  `MlEnrollmentClient`); an ML outage never blocks (per [0026](../decisions/0026-students-and-ml-enrollment.md)).
- **Persona:** school admin. **Source lens:** X4, T8, P5.
- **Acceptance:** a class of ~500 enrolls from one upload with a per-row created/matched/failed report; a
  bulk re-enroll clears a batch of failures in one action; unmatched filenames are surfaced, not silently
  dropped.

### BP11 — Organizing structure: classes/sections + event terms/categories · **Effort M–L · Impact H · BE + FE (+ migration)** · ✅ landed — sliced a/b/c; **all three landed** ([0058](../decisions/0058-product-build-BP11a-student-classes.md), [0059](../decisions/0059-product-build-BP11b-event-categories-calendar.md), [0060](../decisions/0060-product-build-BP11c-teacher-delegation.md))
- **Problem (theme B):** no **class/grade/section** on students, no **term/category/calendar** on events —
  one flat 800-row / 120-event world. Blocks delegation, findability, reporting, and cohort-scoped matching
  all at once. Fails **P3/P5/X5**.
- **Change:** a `student_group`/class (name + grade/section) with membership; `event.term`/`category`/`date`
  labels; grouped + filtered list/calendar views; **teacher delegation scoping** (a teacher sees/runs their
  class + its events). Cohort-scoped *matching* (the ML index-scoping half) is staged into **BP15**.
- **Persona:** school admin + teacher. **Source lens:** P3, P5, X5.
- **Acceptance:** students filter/group by class; events filter by term/category + a calendar/date view; a
  teacher's lists scope to their class(es); no tenant/role leak.
- **Slices (owner-approved plan — HTML explainer + decisions Q&A):** **BP11a** student classes — ✅ landed
  ([decisions/0058](../decisions/0058-product-build-BP11a-student-classes.md)): `student_groups` (one class
  per student, SET NULL on class delete) + a `ClassService` + a `class:manage` perm (admin-only lifecycle,
  `student:manage` reads/assign), the students class filter/badge/selector + a Classes management surface.
  **BP11b** event term/category + calendar — ✅ landed
  ([decisions/0059](../decisions/0059-product-build-BP11b-event-categories-calendar.md)): a free-text term +
  **per-school configurable categories** (a tenant `event_categories` table, seeded with 6 defaults on
  school-create + into existing schools in migration 0014; managed by admins + staff on `event:manage`) + a
  read-only month calendar (List⇄Calendar tabs). **BP11c** teacher delegation — ✅ landed
  ([decisions/0060](../decisions/0060-product-build-BP11c-teacher-delegation.md)): a `teacher_classes` N:M
  join + `events.student_group_id` (the deferred event↔class link) + a `DelegationService` + a teacher list
  **"focus"** scope (owner call: **focus-only**, no hard restrict — convenience, not a boundary), reusing
  **`class:manage`** (no new perm). Cohort-scoped *matching* stays deferred to **BP15**. **BP11 is complete
  (a, b, c).**

### BP13 — Bulk actions & batch review · **Effort M · Impact M · BE + FE** · ✅ landed ([decisions/0061](../decisions/0061-product-build-BP13-bulk-actions-batch-review.md))
- **Problem (theme E):** everything is one-at-a-time — no bulk re-enroll, no bulk archive, **no batch
  confirm/reject** in the needs-review lane, **no multi-select** on photos. At 100+ ambiguous matches, review
  gets skipped (defeating BP5). Fails **P5/X2**.
- **Change (shipped):** the event review lane → a **confidence-sorted checklist** with Confirm/Reject
  selected + a guarded **"Reject all remaining"** (batch confirm/reject reusing BP5's `set_verdict` overlay,
  tenant-safe by construction); **bulk archive/restore** events (a checkbox column + a tenant-scoped
  `set_status_bulk`); **multi-select photo download** (a staff-grid `selectionMode` on `PhotoGrid` +
  BP9's streaming `useDownloadAll`). **Owner call: no auto-confirm** (the lane is confidence-sorted instead
  of a threshold heuristic). Bulk re-enroll already shipped (BP8a/BP10 "Retry failed"). **No migration, no ML
  change, no new permission** — two thin endpoints (`POST /v1/events/{id}/review/batch`, `POST
  /v1/events/bulk-status`).
- **Persona:** school admin + teacher. **Source lens:** P5, X2.
- **Acceptance:** 100 ambiguous matches triaged in a few actions, not 100; several events archived at once;
  several photos downloaded as one zip. **Honest limits:** per-event review (no global queue), no
  auto-confirm, bulk acts on loaded rows (no select-across-all-pages).

### BP14 — Program analytics & trends · **Effort M · Impact M · BE + FE (+ migration)** · ✅ landed ([decisions/0062](../decisions/0062-product-build-BP14-program-analytics.md))
- **Problem (theme G):** dashboards are **point-in-time counts**. Neither the school admin ("how did
  distribution go **this term**? how many of 800 have **ever signed in**?") nor the platform admin (which
  schools **adopted**, which **stalled**) can see trends or a funnel. Fails **T4/P8/X4**.
- **Change (shipped):** a pure `AnalyticsService` composing existing + a few new grouped aggregates into two
  reads — the **school program view** (`GET /v1/analytics/school`, `dashboard:view`: delivery/sign-in/
  engagement rates + per-term rollups + a monthly upload/event trend) and the **estate adoption view**
  (`GET /v1/analytics/estate`, `school:manage`: a per-school funnel staff→students→enrolled→events→distributed
  + a transparent stalled/idle heuristic). **Migration `0016`** adds the one gap — `users.last_login_at`
  (stamped on login, never refresh) — powering "ever signed in". Trends are **derived from timestamps**
  (owner call — no snapshot table/job); "enrolled" is a current funnel, not a historical line. FE: a
  **Program analytics** section folded **into the school Dashboard** (rate cards + a dependency-free CSS trend
  chart + per-term table — no separate nav item, owner's call) + a platform **Estate-health** page (its own
  nav item — stalled alerts + adoption-funnel table). **No ML change, no new permission, no new dependency, no
  new env var.**
- **Persona:** school + platform admin. **Source lens:** T4, P8, X4.
- **Acceptance:** admins answer "how is the program doing this term?" and "which schools are stuck?" without
  a spreadsheet. **Honest limits:** query-only trends (a snapshot table is the scale-up); no login backfill
  (the sign-in rate climbs from launch); the stalled/idle rule is a heuristic, not a model; in-app delivery
  only (outbound email is BP12).

---

> **Deprioritised (owner calls, 2026-07-25).** The three phases below sit at the **back of the queue** so the
> cheaper, higher-urgency phases (BP9–BP11, BP13/BP14 + BP17) land first. **BP12** (distribution) is the
> highest-impact of the three but needs the first outbound-email infra; **BP15** (accuracy) now carries only
> its lighter staleness + reconciliation scope (cohort-scoped matching skipped); **BP16** (lifecycle) is pure
> risk-reduction — the lowest product urgency. They stay fully specced here; re-confirm scope when they come
> off the queue.

### BP12 — Distribution reach: outbound email (to the student account) + share link · **Effort M–L · Impact H · BE + FE (+ infra)** · 📋 proposed · ⏬ **deprioritised → back**
- **Problem (theme C):** delivery is **in-app only** (BP4) — no email/push — so a student (or, for a young
  child, the **parent who uses the student account**) sees photos only by logging in and looking. Across 120
  events the photos are effectively **undelivered**. Fails **X1/T1**. *(Still a **Critical** review finding —
  deprioritised on **effort/infra**, not importance; it needs the first outbound-notification infra in the
  system.)*
- **Change:** drop an **email channel** into BP4's existing `CompositeNotifier` seam (the seam already fans
  out — the lift is the provider + templates); send "photos ready" to the **student account's email**
  (`02` §3.5 — **no separate guardian model**; the address is the parent's for a young child); add a
  **tokenized share link**. Consent/legal stays out-of-band (`00` §1).
- **Persona:** student (+ the parent behind the account) + staff. **Source lens:** X1, T1, P2.
- **Acceptance:** a matched student receives "You're in 12 photos from Sports Day" → deep link **at their
  account email**, without being told out-of-band to log in; staff see delivery status; best-effort + PII-safe.

### BP15 — Accuracy at scale: enrollment staleness + match reconciliation · **Effort M · Impact M · BE + FE (+ migration)** · 📋 proposed · ⏬ **deprioritised → back**
- **Problem (theme H):** no **re-enrollment cadence** as children grow (a stale reference photo silently
  degrades matching); no per-event **expected-vs-matched reconciliation** ("18 of 22 enrolled kids found —
  who's missing?"). Fails **X2/P7**.
- **Change:** an enrollment **staleness** signal + re-enroll prompt; a per-event **"18 of 22 enrolled found"**
  reconciliation view so staff can spot + report misses at a glance.
- **Persona:** teacher + admin. **Source lens:** X2, P7.
- **Acceptance:** stale enrollments surface; staff see who's missing per event and can act.
- **Skipped for now (owner call, 2026-07-25):** **cohort-scoped matching** — narrowing an event to a grade
  (needs BP11's class structure + ML index-scoping) to cut false matches + leakage. Documented, not built;
  revisit later. *(Dropping it is what brings this phase from M–L down to M.)*

### BP16 — Lifecycle & retention at scale · **Effort M · Impact M (risk) · BE + FE (+ migration)** · 📋 proposed · ⏬ **deprioritised → back**
- **Problem (theme I):** no **bulk archive**; no **event hard-delete** (deferred from
  [BP8e](../decisions/0053-product-build-BP8e-student-erasure.md)); no retention/expiry. Years of events
  clutter every flat list. Fails **X3**.
- **Change:** bulk archive; **event hard-delete** (purge media rows + storage objects + matches/detections,
  reusing BP8e's erasure machinery); optional **time-based retention**.
- **Persona:** admin + ops. **Source lens:** X3, X5.
- **Acceptance:** years of events don't clutter every list; an event can be truly deleted end-to-end (rows +
  objects + ML records); an optional retention policy prunes on schedule. *(Deprioritised on **product
  urgency** — pure risk-reduction; safe at the back until the flat lists actually get cluttered.)*

---

## 5. How to use this file

- **Pick the next phase** off the top of §4 — **BP9**, **BP17**, **BP10**, **BP11a/b/c** (organizing
  structure), **BP13** (bulk actions & batch review), and **BP14** (program analytics & trends) have landed.
  The recommended track is **complete**. Everything still open is **parked** (owner call, 2026-07-27,
  [decisions/0063](../decisions/0063-park-remaining-backlog.md)) and tracked in one place —
  [`05-parked-backlog.md`](05-parked-backlog.md): the deprioritised **BP12 / BP15 / BP16**, the parked **BP6
  video timeline**, plus the documented scale-up/polish refinements. Nothing is scheduled; pick an item up only
  on an explicit request + a scope re-confirm.
- **Before building**, re-read the phase's **source lens** in `01` (the acceptance target) and its finding
  in `02` (what breaks + severity), then lock the phase design in a `decisions/` doc (repo convention).
- **Keep `00` honest:** when a capability ships, move it from "dark/absent" to "exposed" in `00`'s
  capability map, and tick this file's phase to ✅.
- **When BP12 / BP15 / BP16 come off the back of the queue,** re-confirm scope first: email/notification
  infra for BP12 (delivery to the **student account**, no guardian model); staleness + reconciliation for
  BP15 (**cohort-scoped matching stays skipped** per the owner unless revisited); bulk archive + event
  hard-delete (reusing BP8e's erasure machinery) for BP16.
