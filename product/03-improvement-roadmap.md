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

### BP4 — Distribution: "Photos are ready" · **Effort L · Impact H · BE + FE (+ migration)** ✅ landed (decisions/0041) — the flagship
- **Problem:** delivery is **strictly pull-only** — nothing reaches the student. The single biggest product gap.
  Fails **X1/T1**.
- **Change (staged):** (a) an **in-app "New photos" state** — a per-student unseen-count + a "You're in N new
  photos" banner (a lightweight `deliveries`/`seen` table + endpoints; no email infra); (b) a staff **"Notify
  students"** action on a distributed event + a "who's been notified" view; (c) **email delivery** ("You're in 12
  photos from Sports Day" → deep link) — net-new notification infra (SMTP/provider), the first such in the system;
  guardian email optional (product value, not compliance).
- **Persona:** student + staff. **Source lens:** T1, X1, P2, D1. **Acceptance:** a student learns photos exist
  **without being told out-of-band**; staff can drive + see delivery. **Migration + new infra — scope carefully.**

### BP5 — Trust & Accuracy loop · **Effort L · Impact H · BE + FE (+ migration)** ✅ landed (decisions/0042)
- **Problem:** `needs_review` + the rich detection audit are **dead data** — no confirm/reject/report-a-miss, no
  feedback loop; thresholds untunable without DB edits. Fails **X2/T3**.
- **Shipped:** a backend-owned **`match_corrections`** overlay (verdict `confirmed`/`rejected`/`added`) keyed on the
  stable **`(media_id, student_id)`** — **no ML change, no cross-seam SQL join**. A staff **needs-review lane**
  (`GET /events/{id}/review`) → **confirm/reject/undo** on the photo detail; **report-a-miss** — staff **add** a missed
  student (they then see + can download) and students **self-serve "this isn't me"** (`POST /me/media/{id}/not-me`,
  membership-checked); **reject → hides the photo + blocks download** (the effective-appearance gate, unit-tested truth
  table). Corrections overlay all 6 gallery reads + the download gate + (revising BP4) the notification targets/roster/
  student signal, and drive the dashboard "N to review" (`raw − resolved`). Migration `0006`; new `match:review` perm.
- **Deferred:** per-school **threshold tuning** in-product (ML-owned `school_thresholds` — a separate write, out of BP5
  scope); reconciling the BP2 list rollups to effective counts; surfacing the `reason` field.
- **Persona:** staff (+ student). **Source lens:** T3, X2, P7. **Acceptance (met):** an ambiguous match can be
  confirmed/rejected and the gallery reflects it; a miss can be reported; corrections persist.

### BP6 — Video end-to-end · **Effort S–M · Impact M · FE only · no migration · no ML** ✅ landed (decisions/0043)
- **Problem:** video is **fully built in ML** (frame extraction, per-frame matching, timestamps) but **dark** — no
  UI renders it. Fails **X6/T6**.
- **Shipped (Core, FE-only):** `video` media now renders in the gallery grid (a `#t=0.1` first-frame **poster** + play
  badge), the **lightbox** + photo-detail (`<video controls>`), and downloads — all off the **same signed URL** the
  `<img>` used (inline-served, range-request-capable). The **event uploader accepts video** (MIME-classified →
  registers the real `media_type`; the register + download paths already supported it). A video's appearances reuse the
  BP5 overlay unchanged. **No backend/ML change, no migration, no new dep.**
- **Deferred:** the "who appears when" **timeline** (needs a new isolated `student_media_appearances` read +
  `GET /media/{id}/timeline`, corrections-overlaid); raising the video **size cap** (`BE_MAX_UPLOAD_MB` + bucket) and a
  stored **poster thumbnail**.
- **Persona:** both. **Source lens:** T6, X6. **Acceptance (met):** a video uploads → processes → plays → downloads;
  its appearances render.

### BP7 — Onboarding & bulk · **Effort M–L · Impact M · BE + FE (maybe migration)** · 🚧 in progress (sliced into BP7a–d)
- **Problem:** setup is manual/one-at-a-time; no bulk import; no first-run guidance; `max_teachers` is the only
  business signal. Fails **X4/P4/T8**.
- **Change:** a **setup checklist** (add staff → enroll students → create event → upload → distribute), **CSV bulk
  student import** (so a class isn't typed one-by-one), reference-photo **preview + quality feedback** so enrollment
  failures self-correct, and staff **edit/disable/resend-invite**. (Self-serve signup / plans / billing / per-school
  analytics remain deferred — flag as a later business-model track.)
- **Sliced into four approve-before-commit sub-phases** (grounded in a current-state exploration): **BP7a** setup
  checklist · **BP7b** reference-photo quality feedback (surface the already-returned-but-discarded ML enroll `detail`;
  1-col migration, no ML change) · **BP7c** staff lifecycle + invite model (server-generated temp passwords shown-once,
  disable/enable — `users.status` already exists, no migration — resend-invite) · **BP7d** CSV bulk student import (the
  flagship: nullable `reference_photo_path` migration → name+email now, photo later; server-generated temp passwords; a
  bulk endpoint looping the reusable `create_student`; add-photo-later). Recommended order = as listed (checklist
  cheapest/highest-P4; BP7c's invite model is reused by BP7d).
  - **BP7a landed** ([decisions/0044](decisions/0044-product-build-BP7a-setup-checklist.md)): a server-composed
    **`setup_checklist`** (5 booleans) on `GET /v1/dashboard` + a guided **`SetupChecklistCard`** that retires once the
    school has distributed. Query-only (no migration/ML); 2 net-new signals (`has_staff`, `has_distributed`), the other
    3 derived from existing counts; four core steps drive progress, "add a teacher" is optional/last.
- **Persona:** staff/admin. **Source lens:** T8, P4, X4. **Acceptance:** a fresh school is guided to first value (**met
  by BP7a**); a class imports from CSV (BP7d); a failed reference photo explains itself (BP7b).

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
