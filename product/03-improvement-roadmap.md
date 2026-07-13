# 03 — Improvement Roadmap (whole product)

> **This file = "what we build, in what order, and why."** It turns the current-state facts in
> `00-knowledge-base.md` and the targets/lenses in `01-product-skills-and-rubric.md` into a **prioritized, phased**
> build plan. It is the durable backlog — a future session can pick up any phase without re-deriving the priority.
>
> **Prioritization is the product specialist's call** (owner-delegated): weigh completing the capabilities, the
> experience/polish, and effort×impact — then sequence. **Consent/legal is out of scope** (owned by legal via school
> contracts); guardian/notification/audit appear only as product/distribution/trust value, never compliance.
>
> _Snapshot: 2026-07-13. Build track name: "from feature-complete to product-complete."_

---

## 1. The sequencing thesis

The owner's read — "functional, but not a product" — decomposes into two kinds of gap:

- **Display gaps (cheap):** the data already flows; the product just doesn't *show* it. Fixing these needs **no
  migration and no ML change** — a query-only backend addition at most, plus frontend. High impact per unit effort.
- **Capability gaps (expensive):** a capability doesn't exist end-to-end (real distribution, a review loop, video
  UI). These need **net-new backend/ML** work.

So the sequence **leads with the cheap, high-visibility surfacing wins** (make the admin product legible, make the
student surface delightful), **then** the flagship capability (real distribution), **then** the rest. Within that, the
student-facing paying value and the buyer-facing "does this feel finished" both get early phases.

**Effort legend:** S ≈ ≤1 focused build phase, mostly one surface · M ≈ multi-surface or a small new backend
capability · L ≈ net-new capability across services (+ migration / infra). **Impact:** H/M/L on the product.

---

## 2. Effort × Impact map

```
        HIGH IMPACT                          LOWER IMPACT
  ┌──────────────────────────────┬──────────────────────────────┐
S │ BP1 Admin command center     │                              │
M │ BP2 List richness & scale    │ BP6 Video end-to-end (S–M)   │
  │ BP3 Student receive (Pinterest)│                            │
  ├──────────────────────────────┼──────────────────────────────┤
L │ BP4 Distribution (flagship)  │ BP7 Onboarding & bulk        │
  │ BP5 Trust & accuracy loop    │ BP8 Ops & reliability        │
  └──────────────────────────────┴──────────────────────────────┘
```

Lead with the top-left (BP1–BP3: high impact, S/M). BP4/BP5 are high-impact but L — the flagship spend. BP6 is a
cheap surfacing of already-built ML. BP7/BP8 are lower product-visibility, done once the loop is complete.

---

## 3. The phased backlog

Each phase is a reviewable slice with its own `decisions/` record, per the repo's docs-first / stop-for-approval
convention. Order = my recommended build order.

### BP1 — Admin Command Center · **Effort S · Impact H · FE + query-only BE · no migration · no ML** ✅ landed (decisions/0038)
- **Problem:** `/dashboard` is the one true placeholder ("…arrives in the next phases"); nav is count-free. Fails
  **D1/P1/T4**. Every number already exists in the DB.
- **Change:** `GET /v1/dashboard` (grouped counts; new `dashboard:view` for admin+teacher) → a real command center:
  student enrolled/pending/**failed**, events, photos, **needs-attention alerts** (events with photos not
  distributed · enrollment failures · matches needing review), quick actions, school name; plus **nav
  information-scent badges** (Students · N failed / Events · N to distribute).
- **Persona:** staff/admin (Linear+Stripe). **Source lens:** T4, D1, P1, P2.
- **Acceptance:** dashboard shows correct live counts + only the non-zero alerts; fresh school → a first-run
  invitation; 403 for students; tenant strictly from the token; gates green.

### BP2 — List data-richness & scale · **Effort M · Impact H · FE + query-only BE · no migration** ✅ landed (decisions/0039)
- **Problem:** the four admin lists (schools/staff/students/events) are thin and count-free, with **no
  search/filter/sort** anywhere. Fails **P1/P3/P5/P8/T5**.
- **Change:** additive count fields on the list responses (event → media/matched/needs-review; student →
  appearances/events; school → admins/teachers-of-max/students/events rollups — reuse BP1's aggregate port methods,
  batched, no N+1); **count columns + status rollups** on each list; **client-side search + sort**; **filter chips**
  (students → enrolled/pending/**failed**; events → active/archived); the **reference thumbnail** on the students
  list; a **school admin roster** on `/schools/[id]`.
- **Persona:** staff/admin. **Source lens:** T5, P5, P8, P3. **Acceptance:** each list is searchable/sortable, every
  row carries the count its job needs, filters work, gates green.

### BP3 — Student Receive Experience · **Effort M · Impact H · FE only · no BE · no ML** ✅ landed (decisions/0040)
- **Problem:** the student gallery is Linear-plain, not the emotional core it should be; no welcome, context, or
  "new since." Fails **P9/T2**.
- **Change:** a **Pinterest-grade** `/me/events` — real aspect-ratio masonry (image is the hero), light event
  context (name/date), a **first-visit welcome**, a **"new since last visit"** cue (client-tracked), a **privacy
  reassurance** ("only you can see these"), a smoother lightbox, and a satisfying **download-all** (client-zips the
  already-entitled signed URLs — no BE change). No other student's name ever appears.
- **Persona:** student (Pinterest). **Source lens:** T2, P9, D1, P7. **Acceptance:** the grid feels image-first;
  first-run + new-since cues render; download-all works; a11y floor holds.

### BP4 — Distribution: "Photos are ready" · **Effort L · Impact H · BE + FE (+ migration, maybe email infra)** — the flagship
- **Problem:** delivery is **strictly pull-only** — nothing reaches the student. The single biggest product gap.
  Fails **X1/T1**.
- **Change (staged):** (a) an **in-app "New photos" state** — a per-student unseen-count + a "You're in N new
  photos" banner (a lightweight `deliveries`/`seen` table + endpoints; no email infra); (b) a staff **"Notify
  students"** action on a distributed event + a "who's been notified" view; (c) **email delivery** ("You're in 12
  photos from Sports Day" → deep link) — net-new notification infra (SMTP/provider), the first such in the system;
  guardian email optional (product value, not compliance).
- **Persona:** student + staff. **Source lens:** T1, X1, P2, D1. **Acceptance:** a student learns photos exist
  **without being told out-of-band**; staff can drive + see delivery. **Migration + new infra — scope carefully.**

### BP5 — Trust & Accuracy loop · **Effort L · Impact H · BE + FE (+ migration)**
- **Problem:** `needs_review` + the rich detection audit are **dead data** — no confirm/reject/report-a-miss, no
  feedback loop; thresholds untunable without DB edits. Fails **X2/T3**.
- **Change:** a staff **needs-review lane** (filter to ambiguous matches → confirm/reject, writing a corrections
  table), a **report-a-miss** ("I should be in this / this isn't me") for staff and students, confidence surfaced
  legibly, and (later) per-school **threshold tuning** in-product. Corrections captured as the feedback foundation.
- **Persona:** staff (+ student). **Source lens:** T3, X2, P7. **Acceptance:** an ambiguous match can be
  confirmed/rejected and the gallery reflects it; a miss can be reported; corrections persist.

### BP6 — Video end-to-end · **Effort S–M · Impact M · mostly FE · no migration**
- **Problem:** video is **fully built in ML** (frame extraction, per-frame matching, timestamps) but **dark** — no
  UI renders it. Fails **X6/T6**.
- **Change:** render `video` media in the gallery + lightbox (poster + player), show its appearances (ideally a
  **timeline** of who appears when — the detection audit already supports it), and download. Upload/process already
  work; the gap is purely surfacing (a small BE read for the timeline if the audit isn't already exposed).
- **Persona:** both. **Source lens:** T6, X6. **Acceptance:** a video uploads → processes → plays → downloads; its
  appearances render.

### BP7 — Onboarding & bulk · **Effort M–L · Impact M · BE + FE (maybe migration)**
- **Problem:** setup is manual/one-at-a-time; no bulk import; no first-run guidance; `max_teachers` is the only
  business signal. Fails **X4/P4/T8**.
- **Change:** a **setup checklist** (add staff → enroll students → create event → upload → distribute), **CSV bulk
  student import** (so a class isn't typed one-by-one), reference-photo **preview + quality feedback** so enrollment
  failures self-correct, and staff **edit/disable/resend-invite**. (Self-serve signup / plans / billing / per-school
  analytics remain deferred — flag as a later business-model track.)
- **Persona:** staff/admin. **Source lens:** T8, P4, X4. **Acceptance:** a fresh school is guided to first value; a
  class imports from CSV; a failed reference photo explains itself.

### BP8 — Ops & reliability · **Effort L · Impact M (mostly risk reduction) · BE/ML (+ migration/infra)**
- **Problem:** a permanently-bad photo looks `pending` forever; no retention/erasure; single-replica enrollment is a
  SPOF/bottleneck; no rate limiting; no access/download audit. Fails **X3/X5/T7**.
- **Change:** a **failed-photo state + retry**, a retention/erasure story, **multi-replica enrollment** (the
  documented Redis-lock Option B), **rate limiting**, and an **access/download audit** (trust, not compliance).
- **Persona:** ops. **Source lens:** T7, X3, X5. **Acceptance:** failures are visible + recoverable; enrollment
  isn't a silent SPOF.

---

## 4. Out of scope (owned by legal/contracts)

Consent capture, parental consent, and compliance machinery (COPPA/GDPR/DPDP) are handled **out-of-band by the legal
team via school contracts** and are deliberately excluded from this roadmap. Where guardian email, notifications, and
access audit appear above, they are included **only** for their product/distribution/trust value — never as
compliance controls.

---

## 5. How to use this file

- **Pick the next phase** off the top of §3 (BP2 follows the landed BP1).
- **Before building**, re-read the phase's **source lens** in `01` (the acceptance target) and its **current-state**
  rows in `00` (what exists), then lock the phase design in a `decisions/` doc (repo convention).
- **Keep `00` honest:** when a capability ships, move it from "dark/absent" to "exposed" in `00`'s capability map,
  and tick this file's phase to ✅.
