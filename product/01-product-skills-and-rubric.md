# 01 — Product Skills & Rubric (whole product)

> **This file = "what good looks like"** for the *entire* product (ML + BE + FE). It is the evaluation lens for
> `02-product-review.md` and the source of targets for `03-improvement-roadmap.md`. Read alongside
> `00-knowledge-base.md` ("what exists").
>
> Three parts: **(§3) the lenses** — a scorable rubric (design + UX + **domain product** lenses), each with a stable
> ID so findings can cite it; **(§4) per-persona quality bar**; **(§5) the targets** — per-journey/per-capability +
> per-view "what good looks like," independent of what exists today.

---

## 1. How to use

- **Reviewing (Phase 2):** for each capability, journey, and screen, walk §3's lenses and compare the current state
  (`00`) to §5's target. Every finding cites a lens ID + a persona bar + a severity.
- **Planning (Phase 3):** every roadmap item traces back to a lens + a target it moves toward.
- **Building (later):** §5 is the acceptance target.

---

## 2. Scope reminder

This rubric judges the product **as a product** — not just the UI. A screen can be pixel-perfect and still fail
**X1 (distribution)** because the photos never reach anyone. Consent/legal is **out of scope** (owned by legal via
contracts); privacy appears here only as *product trust* (scope clarity, "only you can see these"), never as
compliance machinery.

---

## 3. The lenses (scorable rubric)

### A. Design-lead lenses — from the installed `frontend-design` skill

| ID | Lens | Passes when… | Fails when… |
|---|---|---|---|
| **D1** | Thesis-first hero | Opens with the most characteristic, useful thing in its world | Opens with a generic greeting and defers substance ("…in the next phases") |
| **D2** | Typography as personality | Scale/weight/hierarchy do deliberate work | Everything is body-14 in a card; no hierarchy |
| **D3** | Structure encodes meaning | Dividers/labels/groupings carry real information | Structure is decorative or absent |
| **D4** | Motion with restraint | Purposeful micro-interactions | Dead-static where feedback is needed, or scattered effects |
| **D5** | Complexity matches vision / one signature | Boldness spent in one memorable place, quiet elsewhere | Uniformly flat, no signature; or busy everywhere |
| **D6** | Copy from the user's side | Names what people control; active voice; specific | System/phase language; vague; clever-not-clear |
| **D7** | Empty/error as direction | Says what happened + the next move; empty = invitation | Placeholder mood copy; dead-ends |
| **D8** | Quality floor | Mobile, visible focus, reduced-motion, AA contrast | Any broken |

### B. Product/UX heuristics

| ID | Lens | The question it asks |
|---|---|---|
| **P1** | Information scent / JTBD fit | Does the screen show what the *job* needs (counts, roster, next action) — not just stored fields? |
| **P2** | Visibility of system status | Progress, timing, freshness, what's happening now? |
| **P3** | Recognition over recall | Data surfaced in place vs. forcing memory/click-away? |
| **P4** | First-run / onboarding | Is a new/empty account guided to first value? |
| **P5** | Efficiency for scale | Search/filter/sort/bulk/keyboard when there are 200 rows, not 3? |
| **P6** | Error prevention & recovery | Validation, inline retry, undo, *disambiguated* failures? |
| **P7** | Trust & privacy *as product* | Scope clarity ("who can see this"), reference-photo visibility, "only you" reassurance? |
| **P8** | Data density done right (admin) | Tabular numerals, scannable rows, rollups — Stripe-grade? |
| **P9** | Image-first delight (student) | Is the photograph the hero — immersive grid, beautiful lightbox, satisfying save? |
| **P10** | Consistency & vocabulary | Same word for the same action across the whole flow? |

### C. Domain product lenses — specific to *this* product

| ID | Lens | Passes when… | Fails when… |
|---|---|---|---|
| **X1** | **Distribution / delivery effectiveness** | The product **actively gets photos to the right person** — a "your photos are ready" signal, easy save (download-all), optional share | Pull-only: photos are merely *queryable*; the recipient must know to log in and hunt |
| **X2** | **Trust & accuracy loop** | Matches are legible (confidence), **reviewable/correctable**, and users can **report a miss**; thresholds tunable in-product | `needs_review` + the detection audit are dead data; accuracy frozen; DB hand-edits to tune |
| **X3** | **Lifecycle & retention** | Media/records have a clear, predictable lifecycle (retain/archive/delete/expire); failures have a visible state | Append-only forever; no retention; a bad photo looks identical to a pending one |
| **X4** | **Onboarding & business model** | New school/user reaches value fast; **bulk** setup exists; capacity/plan/usage are legible | Manual, one-at-a-time; `max_teachers` the only signal; no analytics/plans |
| **X5** | **Ops, scale & reliability** | Scale limits are acceptable/mitigated; failure modes visible + recoverable; no silent SPOF | Single-replica enrollment SPOF; no rate limiting; silent retries; no audit |
| **X6** | **Media completeness (video)** | Every declared `media_type` is fully usable end-to-end (upload→process→view→download) | Video is built in ML but **dark** in the product |

---

## 4. Per-persona quality bar (split-by-persona)

| | **Student surface** (`/me/*`, gallery/lightbox) | **Staff / admin / platform** |
|---|---|---|
| **Reference** | **Pinterest** — image-first, immersive, warm | **Linear + Stripe** — dense, precise, data-rich |
| **The hero is** | The photographs | The data that drives the next decision |
| **Optimize for** | Delight, trust, "these are *my* photos" | Speed, control, at-a-glance status |
| **Distribution (X1)** | Gets a signal photos are ready; one-tap save | Can *drive* delivery (trigger/announce), see who got what |
| **Density** | Generous, image-bleed | Compact, tabular, scannable |
| **Failure feeling** | "A plain grid of thumbnails, like a file browser" | "A thin 3-column table; I click into everything to learn anything" |

Shared **non-negotiable floor (D8):** responsive, visible focus, reduced-motion, AA contrast; every empty/error
state gives direction (D7).

---

## 5. Targets — "what good looks like"

### 5A. Capability & journey targets (the whole-product level)

**T1 — Distribution / "photos are ready" (X1, P2, D1)** — *the flagship gap.*
When an event finishes processing, the matched students (and, where relevant, a parent) get a **signal** — at
minimum an in-app "New photos" state and, ideally, an email/push: "You're in 12 photos from Sports Day." The student
lands on a ready-made set with a **download-all** and an optional **share link**. Staff can see/trigger this
("Notify students"). *Success:* a student receives photos **without being told out-of-band to log in.*

**T2 — Student receive experience (P9, D1, P7)** — *the emotional core.*
A warm, **image-first** gallery where the photos are the hero (real aspect ratios, generous masonry), light event
context (name, date), a first-visit welcome, a "new since last visit" cue, a privacy reassurance ("only you can see
these"), a smooth lightbox, and a satisfying **save/share**. No other student's name ever appears.

**T3 — Trust & accuracy loop (X2, P7)** — surface confidence legibly; give staff a **needs-review lane** (filter to
ambiguous matches → confirm/reject); let staff/students **report a miss** ("I should be in this / this isn't me");
expose per-school **threshold tuning** in-product. Corrections are captured (foundation for a future feedback loop).

**T4 — Staff command center / dashboards (D1, P1, P8)** — every admin landing answers "what's the state and what do
I do next?": headline stats (students enrolled/pending/**failed**, events, photos distributed, students awaiting
sign-in), **actionable alerts** ("3 enrollments failed," "an event has photos but wasn't distributed"), quick
actions, recent activity. Platform + school + event all get their level of rollup.

**T5 — Efficient management at scale (P5, P8, X4)** — lists have search/filter/sort + **bulk** (CSV student import,
bulk archive); every list row carries the **counts** the job needs (event → #photos/#matched/#needs-review; student
→ enrollment + #appearances; school → capacity used + activity). Admin rosters exist (the school's admins; staff
with status + last sign-in + disable/resend).

**T6 — Video end-to-end (X6)** — a `video` media renders in the product: a poster + player in the gallery/lightbox,
its appearances (ideally a **timeline** of who appears when, which the detection audit already supports), and
download. Upload/process already work; the gap is purely surfacing.

**T7 — Lifecycle & reliability (X3, X5)** — media/records have a visible lifecycle: a **failed-photo state**
(not "looks pending forever") with retry; a retention/erasure story; an access/download audit for trust; enrollment
that isn't a single-replica SPOF; rate limiting. Failure modes are visible and recoverable.

**T8 — Onboarding to first value (P4, X4)** — a fresh school/account is guided: a setup checklist (add staff →
enroll students → create event → upload → distribute), bulk student import so a class isn't typed one-by-one, and
reference-photo **preview + quality feedback** so enrollment failures are self-correcting.

### 5B. Per-view targets (the FE yardstick)

Format: **Job** · **wants to show**. Bar per §4.

- **`/login`,`/change-password`** — get the right person in with trust; a small brand moment, show-password, a
  forgot-password path, live rule feedback, specific errors.
- **`/schools`** (admin) — the estate; per-school **rollups** (admins, teachers of max, students, events, last
  activity) + search/sort.
- **`/schools/[id]`** (admin) — run one school; **the administrator roster** (biggest gap) + capacity used + the
  temp password shown once, copyable.
- **`/dashboard`** (admin) — see T4: stats + alerts + quick actions + school name; first-run checklist for a fresh
  account.
- **`/staff`** (admin) — roster with status + when-added + last-sign-in, capacity ("4 of 10"), resend/disable,
  disambiguated 409s.
- **`/students`** (admin) — enrollment **rollup** (enrolled/pending/**failed** as filter chips), the **reference
  thumbnail**, filter-to-failed, search, **CSV bulk import**; each row hints "in N events."
- **`/students/[id]`** (admin) — the **actual reference photo** (+ quality hint on failure), enrollment status
  **+ timestamp**, a crisp failure→fix, the "appears in" gallery with dates + counts + download-all.
- **`/events`** (admin) — per-event **photo count + #matched + processing progress**, a **needs-attention** cue
  (has photos, not distributed), active/archived filter, search/sort.
- **`/events/[id]`** (admin) — photo/matched/**needs-review** counts; a real **progress + timeline**; a roster
  preview linking to the gallery; consistent action vocabulary; a non-confusing "new uploads pending" message;
  a **Notify students** action (T1).
- **`/events/[id]/upload`** (admin) — running count, per-file progress, **inline retry**, size guidance, a clear
  "you have N photos — Distribute now" hand-off.
- **`/events/[id]/gallery`** (staff) — All / By-student **plus a Needs-review lens** (X2); per-student counts;
  video tiles (X6); select + **download-all**.
- **`/photos/[id]`** (staff) — big image; appearances with confidence + review flag (good today); event context;
  prev/next; confirm/reject (T3).
- **`/me/events`** (student) — see T2: warm image-first grid, context, first-run welcome, "new since," privacy
  reassurance, download-all, and a "you're in N photos" hero.
- **Global** — role-appropriate nav with **information scent** (e.g. "Students · 3 failed"), consistent identity,
  error/404 that route forward, keyboard + focus throughout.

---

## 6. Cross-cutting rubric checklist

- [ ] **X1** The product *delivers* — a "ready" signal + easy save, not pull-only.
- [ ] **X6** Every `media_type` (incl. video) is fully usable end-to-end.
- [ ] **X2** `needs_review`/confidence are actionable (triage, confirm/reject, report-a-miss).
- [ ] **D1 / P1 / P3** Screens open with substance and show the counts/rollups/roster the job needs.
- [ ] **P5 / X4** Lists have search/filter/sort + bulk; rosters + capacity are visible.
- [ ] **P2 / X3** Status, timing, and lifecycle (incl. failure states) are visible.
- [ ] **P4** New/empty accounts are guided to first value.
- [ ] **P9** (student) The image is the hero. **P8** (admin) Numbers are tabular, scannable, rolled-up.
- [ ] **X5** No silent SPOF; failures visible + recoverable.
- [ ] **D7 / D6** Empty + error states give direction in the user's vocabulary; actions keep one consistent name.
- [ ] **D8** Mobile, focus, reduced-motion, contrast.
