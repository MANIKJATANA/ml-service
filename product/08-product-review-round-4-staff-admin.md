# Product Review — Round 4: Staff & School-Admin (pre-release)

**Date:** 2026-08-29
**Scope:** The **staff (teacher)** and **school-administrator** interfaces only — the `(school)` route group and its
components. The student self-view (`(student)/me`), the platform super-admin (`(platform)`), and the parent lens are
**out of scope** for this round (they were the focus of Rounds 1–3; see `product/02`, `product/06`).
**Method:** Static, **code-grounded** walk of the rendered UI — routes, components, hooks, copy, and states read
directly from `frontend/` — exactly as Rounds 1–3 were done. Four parallel exploration passes (admin surface,
teacher surface, the five operational flows, prior-review context) were reconciled against the shipped state in
`CLAUDE.md` + `decisions/`. **No running stack** was available (Docker/live-smoke remains pending), so runtime-only
behaviour (real latency, actual data density, the Supabase PUT contract) is flagged where it matters.
**Purpose:** The **last review before the 1st release.** It answers one question for two personas: *is this software a
school can actually run day-to-day, and what must ship first?*

> **Reading note.** This round deliberately does **not** re-litigate visual design. Rounds 1–3 closed the design bar
> for these surfaces (see §2). The open work is **capabilities and operability at scale**, plus **one strategic
> release-blocker**. Findings already resolved by BP1–BP25 are listed in §7 so they are never re-chased; the ~11
> Round-3 refuted leads (`product/06` §7b) likewise stand refuted.

---

> **⚠ v1 pivot (owner decision, 2026-08-29) — read this first.** After this review was written, the owner set the
> v1 scope: **there is no student login in v1.** Students do not access the app at all. Distribution is
> **staff-mediated** — a teacher or school-admin **downloads a student's photos and shares them (e.g. via WhatsApp)
> themselves.** Consequences for this review: **(1)** the §1 release-blocker "no outbound reach" is **answered by
> product decision**, not by email — **outbound email/SMS is deferred post-v1** (the old BP26 scope folds into the
> parked **BP12**). **(2)** The v1 distribution *mechanism* is a small, **FE-only** new feature — **staff per-student
> "Download all"** (teacher *and* admin), which reuses the exact `useDownloadAll` streaming-zip the student self-view
> already had. This is the **reframed BP26** and the one true pre-release build for distribution. **(3)** The in-app
> **announce → "opened" roster** path and the entire **student surface** (`(student)/me`, BP18 recovery, BP20 arrival,
> BP22 student-side "This isn't me") are **dormant in v1** — shipped, but unused (a possible "v1 hygiene" cleanup,
> noted in `product/09`). Every finding below still stands; only the *distribution* framing changes, flagged inline.

---

## 1. Executive summary

The staff/admin product is **mature and genuinely well-built.** The chrome is consistent and disciplined, the copy is
honest (BP21), state lives in the URL (BP25), destructive actions confirm, bulk selections are stale-safe, and the
hard problems — a stranded pipeline (BP19), credential recovery (BP18), the review loop with a reference face (BP22),
scale-ready lists and galleries (BP9/17) — are solved. A school administrator has a real command center; a teacher is
a capable daily-driver for the core loop. **The pixels are there.**

What stands between this and a confident 1st release is **not design** — it is a small set of **capability and
operability gaps**, headed by one strategic decision:

- **The release mechanism (post-pivot): staff-mediated distribution.** v1 has **no student login and no outbound
  email** — so "delivery" happens through staff: a teacher/admin downloads a student's photos and shares them (e.g.
  WhatsApp). The one gap that blocks this today is that **staff have no per-student "download all"** — they can
  download a single photo, or an event's whole gallery, but **not "every photo of student X across all their events"**
  in one zip (the exact thing a student could do for themselves before). Closing it is small and **FE-only** (reuses
  `GET /students/{id}/media` + `useDownloadAll`), and it *is* the v1 distribution build — the reframed **BP26**.
  Outbound email/SMS (the original BP26 = **parked BP12**) is deferred post-v1.

- **Operability at scale (recommended for release): the one-at-a-time cliffs.** Almost every *bulk* affordance the
  product added stops one step short. There is bulk student **import** but no bulk **delete/disable**; single
  credential **resend** but no cohort resend; bulk photo **enroll** but no **retry-failed** in that dialog (the event
  uploader has one); bulk event **archive** but no bulk staff **invite**. At 800 students / 25 classes / 20 teachers,
  these cliffs turn routine ops into click-marathons.

- **Governance & audit completeness (recommended for release): the log answers half its question.** The access log is
  chronological-only with **no filters** (though the backend event/student filters are already wired — BP8b/BP23 — and
  merely lack UI), **no CSV export**, and there is **no admin-action audit** at all (who disabled/deleted/re-enrolled a
  student is unrecorded). Schools need accountability to adopt.

- **Teacher-role coherence (recommended for release): the second persona is under-finished.** An un-delegated teacher
  silently sees the whole school with no explanation; the setup checklist offers a teacher an "Add a teacher" step
  that dead-ends in a RoleGate redirect; a delegated teacher can *filter by* their class but cannot *see* its roster;
  there is no "what's mine to do" lens. The teacher works, but the role reads as half-built.

- **The rest is polish** — review-loop power tools at scale, the onboarding feedback loop, and a handful of copy/
  discoverability fixes. Valuable, not blocking.

**Bottom line for release:** exactly **one** true blocker (v1 distribution — the small, FE-only staff per-student
download; outbound email deferred to parked BP12), a strong tier of **operability + governance + teacher-coherence**
work that separates "demo-ready" from "school-ready," and a thin layer of polish. The roadmap (`product/09`) tiers them
accordingly.

---

## 2. Design-bar verdict (staff/admin chrome)

Round 3 concluded *"Linear delivered · Stripe substantially closed · Pinterest half-closed."* Pinterest is the student
gallery (out of scope). For the **staff/admin** surfaces specifically, this round confirms:

- **Linear (app chrome) — MET.** A calm, dense, single-accent shell: sidebar nav with information-scent badges,
  breadcrumbs, page headers with a primary/secondary CTA pair, hairline-bordered tables, semantic status pills,
  skeleton loaders, honest empty states, a skip-link, an offline bar, a mobile drawer
  (`components/ui/app-shell.tsx`). Nothing here needs restyling for release.
- **Stripe (dense data/forms) — SUBSTANTIALLY MET.** Rate cards, per-term tables, monthly trend chart, tabular
  numerals on numeric cells, multi-phase dialogs with preview steps (`components/analytics/program-analytics.tsx`,
  the CSV/photo import dialogs). The residue is presentational (a bare estate funnel, a couple of terse cells), not
  structural.

**Implication:** the pre-release work is **functional completeness and operability**, *not* a visual pass. This review
weights features/flows accordingly and does not propose a restyle.

---

## 3. School-administrator walk

The admin owns the school: onboarding, staff, students, classes, events, distribution, galleries/review, analytics,
audit. Each surface below leads with what works, then the **genuine open findings** (already-shipped items excluded).

### 3.1 Dashboard & analytics — *strong*
Adaptive first-run (SetupChecklistCard) → steady-state (stat cards + needs-attention alerts + folded-in program
analytics), retiring the checklist once the school distributes (`dashboard/page.tsx`). Alerts are semantic and
deep-link (`/students?status=failed`, `/events`). This is a genuine command center.

- **R4-A01 (Medium)** — *The onboarding checklist has no feedback loop.* Each step deep-links away (`/students`,
  `/events`) and completing it lands the admin on that list, **not** back on the checklist to see the checkmark tick.
  The satisfying "3 of 4 → 4 of 4" momentum breaks; the admin must manually return to the dashboard to learn they
  progressed. (`dashboard/page.tsx` step CTAs.)
- **R4-A02 (Low)** — *No first-load warmth.* The header reads "Dashboard" until the fetch resolves the school name; a
  first-timer gets no "you're in the right place" cue.
- **R4-A03 (Low)** — *Analytics offer no goal/benchmark context.* Rate cards state a number ("60% open rate") with no
  target, trend-direction call-out, or "is a rising wrong-person rate normal?" guidance. Interpretation is left to the
  admin.

### 3.2 Students — *strong, with scale cliffs*
The richest surface: search/filter/sort/activity-filter, class filter, enrollment pills + failure reasons, avatars,
stale-safe bulk-select→assign-to-class, three ingest paths (single/CSV/bulk-photo), non-destructive
disable/resend/re-enroll, and an engagement card on the detail (`students/page.tsx`, `students/[studentId]/page.tsx`).

- **R4-A04 (High)** — *No bulk delete or bulk disable.* Erasure and disable are **one-at-a-time** on the detail page
  (BP8e/BP18d shipped the single actions). A school off-boarding a graduating cohort of 120 has no batch path.
- **R4-A05 (High)** — *No bulk credential resend.* BP18a gave a student a single "Send new password"; a class of 30
  that lost their logins is 30 detail-page visits. No cohort resend exists.
- **R4-A06 (Medium)** — *Bulk-select acts on the loaded page only.* "Select all" + assign-to-class covers only
  currently-loaded rows (a documented BP9/BP24 honest-limit). Assigning 500 students to a class means paging or the
  paste-emails workaround; there is no "select all N matching."
- **R4-A07 (Medium)** — *Bulk-photo enroll has no retry-failed and no overwrite confirm.* The event uploader kept file
  handles for `retryFailed()` (BP19d); the bulk-**photo** dialog does not — a network blip on 5 of 50 means close →
  re-pick → re-map. It also silently **replaces** an already-enrolled student's photo with no "keep existing" option
  and no confirm (`bulk-photo-dialog.tsx`).
- **R4-A08 (Low)** — *"Add student" never says the photo enrolls a face.* The dropzone reads "An image up to 30 MB";
  a first-timer may read it as a profile picture, not the reference that drives matching.
- **R4-A09 (Low)** — *Bulk-import results show a status pill but not the server's reason.* An `invalid`/`error` row in
  the results phase renders its status, not *why the server rejected it* (the `reason` exists on the result shape but
  isn't surfaced) — so a server-side rejection the client didn't pre-flag is opaque.

### 3.3 Classes — *good, minor gaps*
List + create/rename/delete, a detail with roster, inline add-students, paste-emails bulk-assign (BP24), and a
per-class teachers section (BP11c). Inline dialogs keep context.

- **R4-A10 (Low)** — *No bulk-remove-from-class.* The backend supports clearing a class (`null`), and bulk-**assign**
  exists, but the UI only removes roster members one row at a time.
- **R4-A11 (Low)** — *Grade/Section are write-only.* Captured in the create/edit dialog but never rendered on the list
  or detail beyond the edit form — collected data with no display payoff.
- **R4-A12 (Low)** — *Add-students exclude logic has a known paginated-roster gap* (already documented in-code): an
  unloaded roster page member can reappear as "addable."

### 3.4 Staff — *good, but no scale path*
List with status pills (disabled / awaiting-sign-in / active), last-sign-in + added columns, create-teacher →
shown-once temp password, resend-invite (confirmed when the account is live — BP18b), enable/disable, per-teacher
class assignment (`staff/page.tsx`).

- **R4-A13 (Medium)** — *No bulk staff invite.* Students got CSV bulk import (BP7d); staff did not. A school onboarding
  20 teachers fills the single-email form 20 times.
- **R4-A14 (Low)** — *Edit-classes checkbox list has no search.* A school with 100+ classes gets an unfilterable
  scroll list in the per-teacher "Edit classes" dialog.
- **R4-A15 (Low)** — *Teacher cap is invisible school-side.* The `max_teachers` limit lives only on the platform
  surface; a school admin sees a bare count and discovers the cap via a post-submit 409 (Round-3 R3-A2-04, still open).

### 3.5 Events, upload & distribution — *strong*
List ⇄ Calendar tabs, category/term/class tags (clearable — BP24a), multi-file upload with a bounded pool +
retry-failed + a `beforeunload` guard (BP19d), live status polling with a **30-min** staleness cue + Retry (BP19c),
and a DistributionCard with auto-announce, a review-debt confirm (BP22), and a Notified·Seen roster with a
"Not-opened" filter + 12-row collapse (BP24b). This surface is a highlight.

> **v1 note:** with no student login, the *announce → "opened" roster* half of this surface is **dormant** in v1 —
> nobody logs in to open anything. v1 distribution runs entirely through the new **staff per-student download**
> (§BP26), not the in-app signal. R4-A16/A17 below are therefore *dormant-in-v1* (they describe the announce path);
> their residual value — "which students should I share to?" — is better served by per-student download.

> **Correction to an exploration finding:** one pass reported the staleness threshold as "60s, too short → false
> escalation." That is a **misread** — the threshold is **30 minutes** (`lib/events/status.ts`
> `EVENT_INFLIGHT_STALE_MS`, mirrored by `NEXT_PUBLIC_EVENT_INFLIGHT_STALE_S=1800`). No change needed; a *graduated*
> cue (amber at ~20 min, red at 30) is a nice-to-have, not a fix.

- **R4-A16 (Medium)** — *Re-announce scope is opaque.* After adding a second batch of photos, "Announce again" gives no
  hint of **how many new students** will be notified, and the "last sent" line doesn't flag "new photos added since."
  The admin can't tell a no-op re-announce from a meaningful one.
- **R4-A17 (Medium)** — *The notify roster loads whole.* "Show all" renders the entire matched roster (a documented
  honest-limit); at 500 students the table is unpaginated, and there is **no CSV export** of the "not-opened" cohort —
  the exact list an admin needs to follow up (*dormant in v1* — the announce path; post-v1 the natural bridge to
  outbound delivery, parked BP12).
- **R4-A18 (Low)** — *No live-sync affordance during matching.* The page polls every 2.5s but shows no "checking…"
  indicator; an admin who steps away can't tell the page self-updates.
- **R4-A19 (Low)** — *Category/tag adoption + clearable-tag wording.* Category is a bare optional dropdown with no
  "organize events by type" hint; the tri-state clear option reads "No category," which doesn't obviously *clear* an
  existing tag.

### 3.6 Galleries & review — *strong, power-tools missing*
Three tabs (All / By-student / Needs-review, URL-addressable — BP22), a confidence-sorted batch review lane with a
reference avatar per candidate (BP22), batch confirm/reject + guarded reject-all (BP13), a shared AppearanceEditor
(add/remove, report-a-miss), download + streaming download-all with honest partial/capped/cancelled toasts (BP24b),
and a school-admin download-history panel (BP8b).

- **R4-A20 (Medium)** — *Batch-undo is undiscoverable.* "Reject all remaining" warns "you can undo individual
  rejections later" — but the only undo path is *open the photo → re-add the student via AppearanceEditor.* No one
  finds this without docs; a transient "Undo" affordance (or a "Show hidden/rejected matches" filter) is missing.
- **R4-A21 (Medium)** — *No confidence-threshold selection in review.* BP22 deliberately avoided auto-*confirm*, but
  there is no middle ground either — a staff member can't "select all below 70%" to reject in one gesture; every pair
  is hand-selected. At 200 ambiguous matches this is slow.
- **R4-A22 (Low)** — *Grid-only review + no context.* The review lane is a dense tile grid with no table alternative
  and no event/date context per tile (the "Open photo →" link is the only way to place it).
- **R4-A23 (Low)** — *Add-students search gives no pagination feedback.* At 1000 students, a common-name search shows
  the first page with no "showing X of Y / type to refine" cue.

### 3.7 Audit / access log — *honest but half-featured*
A school-admin-only chronological log (who/when/what/whose), honest about scope ("in-app downloads only, not views or
right-click save"), graceful about deleted actors, paginated newest-first (`audit/page.tsx`).

- **R4-A24 (High)** — *The log can't answer its own question.* No filter UI for actor, student, event, or date range —
  though the **backend event/student filters are already wired end-to-end** (BP8b/BP23), merely lacking a front end.
  "Who downloaded student X's photos?" is page-through-only at thousands of rows.
- **R4-A25 (High)** — *No admin-action audit at all.* Download intent is recorded; **who disabled/deleted/re-enrolled/
  re-invited a student or teacher is not.** For a product handling minors' photos, the absence of an actor trail on
  destructive/governance actions is a real adoption gap for schools.
- **R4-A26 (Medium)** — *No CSV export of the log.* Compliance/records work wants the log in a spreadsheet; there is no
  export.

---

## 4. Teacher walk

Backend truth (`services/backend/.../domain/permissions.py`): a teacher **has** `student:manage`, `event:manage`,
`media:upload`, `job:status:view`, `match:review`, `notification:send`, `dashboard:view`, `gallery:view_all`; a
teacher **lacks** `staff:manage`, `class:manage`, `audit:view`, `school:manage`. The FE gates the delta via
`RoleGate` + nav filtering (`app-shell.tsx`): the teacher nav is **Dashboard · Students · Events** (no Staff, Classes,
Access log). Teachers are **fully capable daily-drivers** for the core loop (enroll → event → upload → match → review
→ announce). The gaps are role-*coherence*, not capability.

- **R4-T01 (High)** — *Un-delegated teacher sees the whole school with no explanation.* The FocusToggle appears only
  when `isTeacher && myClasses.length > 0`; a newly-hired, un-delegated teacher gets the full 800-row list by default
  and **no affordance** telling them delegation exists or that they can ask for it (Round-3 R3-A3-04, still open).
- **R4-T02 (High)** — *The setup checklist offers a teacher a dead-end step.* "Add a teacher" (optional, last) links to
  `/staff`, which RoleGate-redirects a teacher home with no message. The checklist should hide admin-only steps for a
  teacher. (`dashboard/page.tsx`.)
- **R4-T03 (Medium)** — *A delegated teacher can filter by their class but not see its roster.* Class detail is
  `class:manage`-gated (admin-only); a teacher has no read-only "my class roster" view — a capability asymmetry (they
  manage the class's events/students but the class structure itself is opaque).
- **R4-T04 (Medium)** — *No "what's mine to do" lens.* A teacher has no consolidated view of their events needing
  action, their uploads, or their pending reviews — only the same school-wide lists an admin sees, focus-filtered at
  best.
- **R4-T05 (Medium)** — *The class dropdown doesn't distinguish "my" classes.* The events/students class selector lists
  **all** school classes with no visual mark for the teacher's delegated ones; "mine vs. any" is only expressible via
  the separate FocusToggle.
- **R4-T06 (Medium)** — *FocusToggle scope goes stale.* `useMyClasses` fetches once on mount; if an admin delegates a
  class while the teacher's page is open, the toggle/scope won't refresh without a manual reload.
- **R4-T07 (Low)** — *Deep-linking an admin-only page silently redirects.* RoleGate bounces a teacher home with no
  "access denied" feedback — a bookmark to `/staff` just dumps them on the dashboard.
- **R4-T08 (Low)** — *Steady-state checklist noise for a teacher hired pre-distribution.* A teacher who joins before
  the school's first distribution sees the admin onboarding checklist ("Enroll your first student"), implying work
  that isn't theirs.

---

## 5. The five operational flows (cross-cutting)

The persona walks above are organized by surface; this section reads the **jobs-to-be-done** end-to-end and surfaces
the cross-cutting friction (findings already listed above are referenced, not repeated).

1. **Onboard (first-run).** Elegant adaptive checklist; the gap is the **feedback loop** (R4-A01) and forward
   guidance ("great — now create an event"). The teacher variant dead-ends (R4-T02, R4-T08).
2. **Get students in.** Three solid paths with pre-flagging and one-time-credential guards. Cliffs: bulk-photo
   retry/overwrite (R4-A07), the reference-photo copy (R4-A08), the opaque server-reject reason (R4-A09), and — for
   recovery — no cohort resend (R4-A05). The **enrollment-failure fix** is discoverable but the "Fix now" action sits
   in the header while the explanation sits mid-page (**R4-F01, Low** — put a "Replace photo" button *inside* the
   EnrollmentFailureNote).
3. **Run an event.** The strongest flow: upload resilience (BP19d), staleness + retry (BP19c), auto-announce +
   review-debt confirm (BP22). Residual friction is **discoverability** — the dashboard alert names a count but the
   admin still hunts for the event and the Process button (**R4-F02, Medium** — deep-link the "N events to match"
   alert straight to the event, and highlight Process); plus re-announce opacity (R4-A16) and the live-sync cue
   (R4-A18).
4. **Fix mistakes.** Recoverability is genuinely good (disable-not-delete, resend, retry-failed, tri-state clear,
   honest erasure copy). The gaps are **undo-discoverability in review** (R4-A20) and the absence of an **erasure
   grace/undo** and **data-export-before-delete** (**R4-F03, Medium** — an instant, irreversible delete with no undo
   window; and no GDPR-style export of a student's record before erasure).
5. **See results.** Galleries window well (BP9/17); download is honest (BP24b). Gaps: the lightbox doesn't auto-page
   at its end (**R4-F04, Low** — reaching the last loaded tile requires closing → scrolling → reopening), partial
   download failures don't name the failed files (**R4-F05, Low**), and analytics lack date-range filtering (R4-A03).

---

## 6. Consolidated findings

Severity: **Blocker** (undermines the product's purpose at release) · **High** (a real school hits this in week one) ·
**Medium** (friction at scale) · **Low** (polish). "Maps to" points at the `product/09` roadmap phase.

| ID | Finding | Sev | Maps to |
|---|---|---|---|
| **R4-D00** | v1 distribution: staff have **no per-student "download all"** to grab a student's photos and share them (WhatsApp) — the one gap in the staff-mediated model | **Blocker** | **BP26 (v1)** |
| R4-A17 | Notify roster loads whole; no CSV export *(dormant in v1 — announce path)* | Low (v1) | parked BP12 |
| R4-A16 | Re-announce scope opaque *(dormant in v1 — announce path)* | Low (v1) | parked BP12 |
| R4-A04 | No bulk delete/disable of students | High | **BP27** |
| R4-A05 | No bulk credential resend for a cohort | High | BP27 |
| R4-A13 | No bulk staff invite (CSV) — students have it, staff don't | Medium | BP27 |
| R4-A07 | Bulk-photo enroll: no retry-failed, no overwrite confirm, no "keep existing" | Medium | BP27 |
| R4-A06 | Bulk-select acts on the loaded page only (no "select all N matching") | Medium | BP27 |
| R4-A10 | No bulk-remove-from-class | Low | BP27 |
| R4-A24 | Access log has no filter UI (backend filters already wired) | High | **BP28** |
| R4-A25 | No admin-action audit (disable/delete/re-enroll/re-invite unrecorded) | High | BP28 |
| R4-A26 | No CSV export of the access log | Medium | BP28 |
| R4-T01 | Un-delegated teacher sees the whole school, no explanation | High | **BP29** |
| R4-T02 | Setup checklist offers a teacher a dead-end "Add a teacher" step | High | BP29 |
| R4-T03 | Delegated teacher can't see their class roster (read-only) | Medium | BP29 |
| R4-T04 | No teacher "what's mine to do" lens | Medium | BP29 |
| R4-T05 | Class dropdown doesn't mark "my" classes | Medium | BP29 |
| R4-T06 | FocusToggle scope goes stale on live delegation change | Medium | BP29 |
| R4-T07 | RoleGate deep-link redirect is silent (no "access denied") | Low | BP29 |
| R4-T08 | Steady-state checklist noise for a pre-distribution teacher | Low | BP29 |
| R4-A20 | Batch-undo in review is undiscoverable; no "show hidden matches" | Medium | **BP30** |
| R4-A21 | No confidence-threshold selection in the review lane | Medium | BP30 |
| R4-A22 | Review is grid-only, no table view, no per-tile context | Low | BP30 |
| R4-A23 | Add-students search gives no pagination feedback | Low | BP30 |
| R4-A01 | Onboarding checklist has no completion feedback loop | Medium | **BP31** |
| R4-F02 | Dashboard "to match" alert doesn't deep-link to the event's Process | Medium | BP31 |
| R4-F01 | No inline "Fix now" in the EnrollmentFailureNote | Low | BP31 |
| R4-A08 | "Add student" photo field doesn't say it enrolls a face | Low | BP31 |
| R4-A09 | Bulk-import results don't surface the server-reject reason | Low | BP31 |
| R4-A18 | No live-sync affordance during matching poll | Low | BP31 |
| R4-A19 | Category adoption hint + clearer "clear tag" wording | Low | BP31 |
| R4-A02 | No first-load warmth on the dashboard | Low | BP31 |
| R4-A03 | Analytics lack goal/benchmark/date-range context | Low | BP31 (partial → parked BP15/16) |
| R4-A11 | Class grade/section are write-only | Low | BP31 |
| R4-A14 | Edit-classes checkbox list has no search | Low | BP31 |
| R4-A15 | Teacher cap invisible school-side (R3-A2-04) | Low | BP28/BP31 |
| R4-F03 | Erasure is instant (no undo/grace) + no data-export-before-delete | Medium | **parked BP16** |
| R4-F04 | Lightbox doesn't auto-page at its end | Low | BP30 |
| R4-F05 | Partial download failures don't name the failed files | Low | BP31 |

---

## 7. Already shipped — do NOT re-chase

These were open in prior rounds and are **landed** (BP18–BP25 all committed; the Round-3 context pass mislabeled them
as "approved, not shipped" — corrected here):

- **Pipeline resilience** — stranded-event unstick + DLQ consumer + `failed` event state + failure metrics + stall
  cue (BP19a–d, decisions/0069–0072). *Do not re-file "stuck event is invisible."*
- **Account recovery & credential safety** — student/staff resend, last-admin guard, shown-once close-guards, session
  revocation on password change, student disable (BP18a–d, 0065–0068).
- **Copy/honesty** — one Match/Announce grammar, true privacy scope, the "how matching works" explainer + confidence
  legend, honest erasure/audit copy, 30 MB uploader hint (BP21a–b, 0073–0074). *The "distribution vocabulary" and
  "Only you can see these" leads are closed.*
- **Arrival & review** — newest-first arrival + actionable banner (BP20), reference face in the review tile +
  URL-addressable tabs + announce-time review-debt confirm (BP22, 0076).
- **Floor sweep** — AA contrast pass, URL state on all lists, per-page titles, skip-link, responsive calendar,
  non-semantic category colors, offline hint, search highlight (BP25, 0077). *"No URL state" and "category colors speak
  status" are closed.*
- **Instrumentation** — uploader/creator attribution, `last_login_at`, honest reach (announced∩opened), savers,
  first-open trend, verdict-rate quality, activity filters, estate age/stalled axes (BP23, 0078).
- **Two-way doors** — clearable event tags, CSV `class` column + paste-emails, honest partial downloads,
  create-teacher refresh, notify-roster filter/collapse (BP24a–b, 0079–0080).
- **Scale & richness** — server pagination + infinite lists + windowed grids + streaming zip (BP9), list counts +
  search/sort (BP2), thumbnails (BP17), classes/terms/delegation (BP11), bulk archive + batch review (BP13),
  analytics (BP14), audit table + rate-limiting + erasure (BP8).

The ~11 Round-3 **refuted** leads (`product/06` §7b: L1–L4, L11, L20–L25) remain refuted — do not re-open.

---

## 8. Honest limits carried into release (documented, accepted)

These are known and *acceptable* for a 1st release; they are scale-ups, not defects. Naming them here prevents a
future reviewer from re-filing them as findings:

- **Offset pagination** everywhere (keyset is the >10K-row scale-up).
- **In-app delivery is dormant in v1** — distribution is staff-mediated (download → WhatsApp, §BP26); the notifier
  seam + `log` channel exist, but real outbound to students is the parked BP12 (post-v1).
- **Roster/appearance reads fetch matched ids** (BP9 de-rostering); the notify roster and `/me` gallery still fetch
  their id-list whole (bounded per event).
- **Raw-ML list counts vs. overlay-corrected** — the events-list "N to review" pill is raw ML; the DistributionCard +
  review tab are overlay-correct (a documented BP22 divergence; galleries are the effective source of truth).
- **Per-event review, no global queue** — review happens inside an event by design.
- **Fire-and-forget download audit** — only in-app save intent is recorded (not views/right-click).
- **Fixed-window rate limiting**, **single-replica ML enrollment** (Redis-lock Option B is config-gated), **no login
  backfill** (analytics forward-only from launch), **synchronous thumbnails** (async is the scale-up).

---

## 9. Method, confidence & caveats

- **Confidence:** High on *structure, copy, states, gating* (read directly from source). Medium on *runtime feel*
  (latency, density, the Supabase upload/download contract) — **no live stack** was available; a click-through smoke
  across F2–F6 + a Docker `buffalo_l` enrollment run remain the outstanding real-world verifications (tracked in
  `product/05`). None of the §6 findings depend on runtime behaviour to be true.
- **Corrections applied during synthesis:** the 30-min staleness threshold (not 60s); BP18–BP24 are shipped (not
  pending); "no URL state" and "category-color collision" are closed by BP25.
- **v1 pivot (2026-08-29), applied throughout:** no student login in v1 → distribution is staff-mediated (download →
  WhatsApp); outbound email deferred to parked BP12; the reframed **BP26** is the small FE-only staff per-student
  download-all; the student surface + announce/opened path are dormant-in-v1 (shipped, unused).
- **Next:** the roadmap in `product/09` tiers these findings into approve-before-build phases (BP26–BP31 + parked
  call-outs). Per the working rule, **a phase starts only on owner pick + scope re-confirm** — this review schedules
  nothing.
