# 00 — Product Knowledge Base (whole product)

> **Load this file first.** It is the durable, single-source reference for the **entire product** — the ML
> face-recognition service, the FastAPI backend, and the Next.js frontend — covering *what it is*, *who uses it*,
> *the end-to-end journeys*, *the data*, and *the current state of every capability and screen*. It exists so a
> future session (human or agent) can reason about the product and make suggestions **without re-exploring the
> codebase**.
>
> **This file = "what exists."** Companion `01-product-skills-and-rubric.md` = "what good looks like" (the lens +
> targets). `02-product-review.md` scores one against the other; `03-improvement-roadmap.md` sequences the fixes.
>
> **Scope note:** this supersedes the earlier `frontend/product/` docs — the whole product, not just the FE.
> **Maintenance:** when a capability, endpoint, field, enum, or screen changes, update the relevant row here in the
> same change. Drift between this doc and the code is a bug.
>
> _Snapshot: 2026-07-13 · All three services v1 feature-complete + hardened. Consent/legal is handled out-of-band
> by the legal team via school contracts and is intentionally out of this product analysis' scope._

---

## 1. What the product is

A **multi-tenant, face-recognition service that distributes event photos (and video) to the students who appear in
them.** A school runs an event, staff bulk-upload the media, the ML service matches faces against enrolled students,
and each student is meant to receive exactly the photos they're in — without anyone hand-sorting thousands of files,
and without leaking other children's images into a shared album.

**Value proposition:** turn "a drive of 2,000 unsorted event photos nobody looks through" into "every student
privately gets their photos." The manual alternative (tagging by hand) doesn't scale; the naive alternative (one
public gallery) is a privacy problem.

**The core loop:**

```
enroll student (reference photo → 512-d face embedding, per-school index)
   └─► create event ─► upload media ─► PROCESS (ML matches faces per photo/frame)
                                             └─► galleries: staff see who's in each photo
                                                            student sees only their own photos → download
```

> ⚠️ **The loop's last arrow is weaker than it looks.** "Distribute" today means "the photos become *queryable* by
> the student if they log in and browse." There is **no delivery/notification** — see §5 and §7b. For a product
> whose name is *distribution*, this is the single biggest product gap.

**Multi-tenant / B2B2C.** The **school is the tenant** (buyer + administrator); the **student is the consumer** (the
emotional end-user of the photos). Every record is scoped to one `school_id`; there is no cross-school visibility.
This split is why the quality bar splits (see `01`): admin surfaces optimize for control/speed, the student surface
for delight/trust.

---

## 2. The three services & product-level architecture

| Service | Path | Stack | Product role |
|---|---|---|---|
| **Frontend (FE)** | `frontend/` | Next.js 16 + React 19 | The UI for all personas; a **BFF** that proxies the backend and holds JWTs in HttpOnly cookies |
| **Backend (BE)** | `services/backend/` | FastAPI (Python) | The "core system": auth/RBAC, onboarding, students, events, media, galleries, download; enqueues ML jobs; reads ML results |
| **ML service** | `services/ml_service/` | FastAPI + workers | Face **enrollment** (sync HTTP) + **inference** (async queue workers): detect → embed → per-school vector search → decide → persist matches |

**Data flow:** BE and ML share one Postgres. BE enqueues **one event job** to Redis; the ML **worker** reads the
event's media roster, runs the pipeline, writes `matches` + a detection audit, and writes the backend's own
event/media status columns directly. BE just **reads** its own status rows (no poller). Photo **bytes never transit
BE or ML** — the browser uploads/downloads **directly to Supabase Storage** via short-lived signed URLs the backend
mints.

**Constraints that shape product decisions** (keep these in mind so suggestions stay realistic):
- **BFF + HttpOnly cookies:** browser only calls same-origin `/api/**`; JWTs never reach JS. New screens fetch
  through this layer.
- **Bytes direct-to-Supabase:** no server-side image proxy; **no thumbnails/derivatives** exist (full-res only, or
  Supabase transforms — not wired).
- **No notification infrastructure** (email/SMTP/push) exists anywhere in v1 — any "notify" feature is net-new BE work.
- **SWR polling, no websockets:** "real-time" today = polling with an auto-stopping interval.
- **Single-replica enrollment:** ML serializes enrollment writes fleet-wide (a SPOF + bottleneck; see §7c).
- **Backend data surface is already rich:** most *display* improvements need **no backend change** (see §7 "dark
  data"); the few that do are flagged in `03`.

---

## 3. Personas & jobs-to-be-done

| Persona | Who | Primary job (JTBD) | Emotional context | Success = | Lands on |
|---|---|---|---|---|---|
| **platform_admin** | Operator of the service (our company) | Onboard a school + its first admin | Back-office, infrequent | A school is live with a working admin | `/schools` |
| **school_admin** | School IT/office manager | Stand up the school: staff, students+enrollment, events, oversight | Accountable for the whole setup; wants control + visibility | Students enrolled, events distributed | `/dashboard` |
| **teacher** | Staff running events | Create event → upload → distribute → browse galleries | Doing it *alongside* teaching; wants it fast | Photos distributed with minimal friction | `/dashboard` |
| **student** | The recipient | Find + download the photos they appear in | Personal, low tech-tolerance, cares about *their* memories | Sees their photos fast; downloads; feels it's private | `/me/events` |
| **(parent/guardian)** | *Not modeled* | *(For young children, the real recipient/engager)* | — | — | *absent* |

Notes:
- **teacher ⊂ school_admin** in capability *except* staff management (only `school_admin` adds teachers).
- A **student** is both a data record (a `students` profile + reference photo) **and** a `role=student` login,
  created together by staff.
- **No parent/guardian persona exists.** Product-relevant (a parent is the real recipient/engager for a young
  child, and the natural target for "photos ready" notifications) — but **consent/legal is out of scope here**
  (handled by legal via contracts), so guardian is treated as an *optional distribution/experience* consideration,
  not a compliance requirement.

---

## 4. System-wide data model & status vocabulary

```
School (tenant)
  ├─* User            role ∈ {platform_admin*, school_admin, teacher, student}   (*school_id null)
  ├─* Student  ──1:1─ User(role=student)                (profile + login)
  └─* Event
        └─* Media (image|video)
              └─* Appearance   (Media × Student, produced by the ML match pipeline: confidence, needs_review)
```

- **School** — the tenant. `max_teachers` caps teacher logins (the *only* quota in the system).
- **User** — any login. `must_change_password` forces a first-login reset (staff/admin temp passwords are **server-generated + shown once**, BP7c; students' are still staff-set until BP7d).
- **Student** — face-enrolled profile linked 1:1 to a `role=student` login. `reference_photo_path` (Supabase);
  `enrollment_status` = ML result.
- **Event** — media container. `processing_status` = distribution job state; `status` archives it.
- **Media** — one uploaded photo/video. Bytes in Supabase; row is metadata + `processing_status`.
- **Appearance** — "student X is in media Y" + `confidence` + `needs_review`, produced by ML; read via gallery
  endpoints. The ML side *also* persists a far richer per-frame/per-face **detection audit** (see §7c).

### Status enums (the product's whole state vocabulary)

| Enum | Values | Notes |
|---|---|---|
| `role` | platform_admin · school_admin · teacher · student | drives nav, routing, RBAC |
| `School.status` | active · suspended | school pill |
| `User.status` | active · disabled | staff status (+ `must_change_password` → "Awaiting sign-in") |
| `Student.enrollment_status` | pending · enrolled · failed | `failed` = no/blur face or ML down; the specific reason (`no_face`/`ml_unavailable`/`error`) is now recorded + shown (BP7b) |
| `Event.status` | active · archived | archived = hidden from workflows, kept for records (no hard delete) |
| `Event.processing_status` | not_started · queued · processing · completed | polled live |
| `Media.processing_status` | pending · completed | per-photo; a permanently-bad photo *looks* pending (no error state) |
| `media_type` | image · video | video renders + uploads in the UI (BP6); still no per-frame timeline UI |

**Timing/counts that exist in the data** (mostly unrendered — see §7 "dark data"): `created_at`/`updated_at`
everywhere; `Event.enqueued_at` + `Event.completed_at`; `Media.completed_at`; `EventStatus.{pending,completed,total}`;
`media_count` on both `StudentInEventResponse` and `EventForStudentResponse`; per-appearance `confidence` +
`needs_review`.

---

## 5. End-to-end journeys

**J1 — Onboard a school** *(platform_admin)*: `POST /v1/schools` → `POST /v1/schools/{id}/admins` (server-gen temp
password shown once; **BP7c** adds admin disable/enable + resend-invite on `/schools/{id}/admins/{uid}`).
Gaps: manual only (no self-serve); **no admin roster** afterwards (add-only).

**J2 — Set up staff** *(school_admin)*: `POST /v1/staff` (capped at `max_teachers`; 409 on cap/duplicate; server-gen
temp password shown once). **BP7c** adds **disable/enable** (`PATCH /v1/staff/{id}`) + **resend-invite**
(`POST …/{id}/resend-invite`). Remaining gaps: no rename/edit (users have no name column); no bulk (BP7d).

**J3 — Enroll a student** *(staff)*: mint upload URL → browser PUTs reference photo to Supabase → `POST /v1/students`
creates profile + login + fires **synchronous ML enrollment** → `enrollment_status`. Retry via
`POST /students/{id}/enroll`. **BP7b** now shows a **specific `failed` reason + fix** (no_face/ml_unavailable/error),
was generic. Remaining gaps: one-at-a-time (no CSV bulk, BP7d); no reference-photo **preview** / **in-place replace**
(BP7d — so a bad-photo fix is still delete-and-re-add).

**J4 — Run an event** *(staff)*: `POST /v1/events` → multi-file upload (browser→Supabase→`POST …/media`, status
`pending`) → **`POST /v1/events/{id}/process`** enqueues one event job → poll `GET …/status`. Gaps: no per-photo
management; no processing **timeline/duration**; a post-distribute upload flips the pill Completed→Not-started.

**J5 — ML distribution** *(automatic)*: worker reads the media roster → per photo/frame **detect → embed → search
(top-K=2) → decide (threshold + gap) → dedupe** → writes `matches` (+ `needs_review`) + the detection audit → marks
each media `completed`, then the event `completed`. Reproducible (model versions + thresholds stamped per match).

**J6 — Staff browse & triage** *(staff)*: event gallery (All / By-student / **Needs review**), photo detail with
appearances (confidence + verdict) → **confirm/reject/undo + report-a-miss** (BP5, decisions/0042), download any
in-school media. Gaps: no download-all, no video timeline.

**J7 — Student receives photos** *(student)* — **the weak journey**: the student must **know to log in**, open
`/me/events`, filter by event, open a photo, download it one at a time. **There is no trigger** — no email/push/
share telling them (or a parent) photos exist. No "new since last visit," no download-all, no context (date/where).

**J8 — Enrollment/inference reproducibility & model swap** *(ops)*: per-school FAISS index, `meta.version`
cache-invalidation, fail-loud on model-version mismatch; model swap = offline re-embed + atomic index swap.

---

## 6. Capability map across services (exists / exposed / dark)

| Capability | Built in | Exposed in product? | Notes |
|---|---|---|---|
| Enroll student by photo | ML + BE + FE | ✅ | replace-not-append; per-photo failure isolated |
| Match faces in **images** | ML | ✅ | threshold + top-K=2 + gap; dedupe best per (student,media) |
| Match faces in **video** | ML | ✅ (BP6) | full FPS frame pipeline + timestamps built; **video now renders + uploads + plays + downloads** in the UI (decisions/0043). Deferred: the per-frame "who appears when" timeline UI |
| Per-school tenant isolation | ML + BE | ✅ | structural; no cross-school search |
| Reproducibility / model versioning | ML | ✅ (internal) | versions + thresholds stamped per match |
| `needs_review` (ambiguous match) + corrections | ML → BE → FE | ✅ (BP5) | **trust loop landed** (decisions/0042): a staff needs-review lane (`GET /events/{id}/review`) → confirm/reject/undo, report-a-miss (staff add / student "this isn't me"), a backend `match_corrections` overlay that **hides rejected + blocks download** and feeds galleries/dashboard/notifications. Threshold-tuning UI still deferred |
| Per-face **detection audit** (timeline, candidates) | ML | ❌ **dark** | rich per-frame/per-face data; only the dev test UI renders it |
| Confidence score | ML → BE → FE | ⚠️ partial | photo-detail only; not on tiles/lists/dashboards |
| Event processing status + counts | BE + FE | ✅ | live polling; per-photo counts exist |
| Galleries (event↔student↔media) | BE + FE | ✅ | All/By-student; student self-view |
| Download (entitlement-scoped) | BE + FE | ✅ | signed URL; staff any in-school, student only own |
| **Notify / deliver / share** | BE + FE (BP4) | ⚠️ partial | **in-app delivery landed** (decisions/0041): authoritative student "new photos" signal + staff notify/auto/roster + a multi-channel notifier seam (`log` now). Still **no outbound push** (email/WhatsApp are future channels; auto is in-app only) and no share-link |
| Dashboards / analytics / counts | BE + FE (BP1) | ⚠️ partial | **school command center landed** (decisions/0038): `GET /v1/dashboard` rollups + needs-attention + nav scent; list-row counts + platform/analytics rollups still pending (BP2+) |
| Search / filter / sort on lists | FE (BP2) | ✅ | all four admin lists (schools/staff/students/events): client search + sort + status/enrollment filter chips + per-row counts (decisions/0039). **Bulk** actions still absent (BP7). |
| Self-serve onboarding / bulk import / billing | BE + FE (BP7a) | ⚠️ partial | **first-run setup checklist landed** (decisions/0044) guiding a fresh school to first value; **bulk CSV import (BP7d), self-serve signup, and billing still absent**; `max_teachers` is the only quota |
| Retention / hard-delete / audit log | — | ❌ **absent** | archive-not-delete; no retention; no access audit |
| Consent / compliance | — | ⛔ out of scope | handled by legal via school contracts |

---

## 7. Current state per surface

### 7a. Frontend — views (condensed; see also §8 design system)

Route map (17): `(auth)` `/login` `/change-password` · root `/` + `error`/`not-found`/`global-error` · `(platform)`
`/schools` `/schools/[id]` · `(school)` `/dashboard` `/staff` `/students` `/students/[id]` `/events` `/events/[id]`
`/events/[id]/upload` `/events/[id]/gallery` `/photos/[id]` · `(student)` `/me/events`.

| View | Purpose | Renders today | Dark data / key gap |
|---|---|---|---|
| `/login`,`/change-password` | Get the right person in | Centered card; email+password; forced change | No recovery, no show-password, no brand moment |
| `/schools` | Platform estate + create | Table [name · **admins · teachers/max · students · events** · status] + search + sort (BP2) | Bulk still absent |
| `/schools/[id]` | Run one school | Info + **rollup StatCards** + **admin roster** + Add-admin dialog (BP2) | — |
| `/dashboard` | Staff home | **Command center (BP1)**: school name, stat cards (students/events/photos), needs-attention alerts, quick actions; **first-run setup checklist (BP7a)** that guides enroll→event→upload→distribute and retires once distributed | Now real; list-row counts + search/filter are BP2 |
| `/staff` | Manage teachers | Table [email · status · **added** · actions] + search + sort + **disable/enable + resend-invite** + shown-once temp password + a teacher count (BP7c) | No rename/edit (no name column); "of M" capacity is platform-side |
| `/students` | Enroll + keep healthy | Table [avatar+name · email · **appears-in counts** · enrollment] + enrollment filter + search + sort (BP2) | No reference **thumbnail** (needs a signed-URL endpoint — deferred); no bulk (BP7) |
| `/students/[id]` | Fix one student + photos | Card + Re-enroll/Delete + "Appears in" gallery | No reference-photo view; no enrollment timestamp; no confidence in "appears in" |
| `/events` | All events at a glance | Table [name · date · **photos · matched · needs-review** · processing] + active/archived filter + search + sort (BP2) | Per-event management still light |
| `/events/[id]` | Run one event | Info + Photos card (progress + Upload/Process) | No student roster/match summary; no timeline; confusing Completed→Not-started flip |
| `/events/[id]/upload` | Bulk upload | Multi-file dropzone + per-file progress | No inline retry; no size guidance; no "distribute next" hand-off |
| `/events/[id]/gallery` | Browse + triage | Tabs All / By-student / **Needs review (N)** (BP5), masonry grid | No download-all; grid plain |
| `/photos/[id]` | Inspect + **correct** one photo | Big image + appearances (confidence + verdict) → confirm/reject/undo + add-a-missed-student (BP5) | Only place confidence shows |
| `/me/events` | Student "My Photos" | **Pinterest-grade (BP3)** + **authoritative "new photos" banner + nav badge (BP4)**: warm hero; natural-aspect **masonry** w/ hover-download; **download-all** (client-zip); appearances hidden; mark-seen on unmount | Lightbox lacks per-photo event context (deferred) |

### 7b. Backend — 45 endpoints + the distribution model

**Endpoint inventory (by area):** Auth (`/v1/auth/{login,refresh,change-password,me}`) · Dashboard
(`GET /v1/dashboard` — BP1, `dashboard:view`) · Schools
(`POST/GET /v1/schools`, `GET /v1/schools/{id}`, `POST /v1/schools/{id}/admins`, `GET /v1/schools/{id}/admins` — BP2
roster; list responses carry rollups) · Staff (`POST/GET /v1/staff`) ·
Students (`upload-url`, `POST/GET /v1/students`, `GET/DELETE /v1/students/{id}`, `POST …/{id}/enroll`) · Events
(`POST/GET /v1/events`, `GET/PATCH /v1/events/{id}`, `POST …/{id}/process`, `GET …/{id}/status`) · **Notifications
(BP4)** (`POST /v1/events/{id}/notify`, `GET /v1/events/{id}/notifications` — staff; `GET /v1/me/notifications`,
`POST /v1/me/notifications/{id}/seen` — student) · Media
(`…/media/upload-url`, `POST/GET …/media`, `GET /v1/media/{id}`) · Galleries (`GET …/{id}/students`,
`…/students/{sid}/media`, `/v1/students/{id}/{events,media}`, `/v1/media/{id}/appearances`) · Self (`/v1/me/{events,media}`)
· Download (`GET /v1/media/{id}/download` → signed URL, staff-any / student-own) · Health (`/healthz`,`/readyz`,`/metrics`).

**The distribution mechanism (updated by BP4).** In-app delivery now exists: an event is **announced** to matched
students (auto on completion, or a staff "Notify students" push), which drives an authoritative, cross-device
**"new photos"** signal (`GET /v1/me/notifications` → a nav badge + banner; `…/seen` clears it) and a staff
Notified·Seen roster. **Outbound push (email/WhatsApp) is still absent** — a `log` channel + a pluggable multi-channel
seam ship now; auto drives only the in-app signal. No SMS/share-link.

**Lifecycle & privacy posture:** events/media are **archive-not-delete** (no hard delete, no retention/expiry).
Failed photos stay `pending` (no error state). Deleting a student does ML-delete-first (502 if ML down) then FK
cascade — but **historical `matches` for deleted students are silently skipped** in gallery reads (not purged).
**No access/download audit log.** Consent = out-of-band (legal/contracts). RBAC is static role→permission; tenant
`school_id` always from the token (platform routes excepted).

**RBAC:** platform_admin→`school:manage`; school_admin→`staff/student/event/media/job:status/gallery:view_all` +
`dashboard:view` (BP1) + `notification:send` (BP4); teacher→ same minus `staff:manage`; student→`gallery:view_own`.

### 7c. ML service — capabilities & limits

- **Enrollment:** detect largest face per reference photo → 512-d L2-normalized ArcFace embedding → **replace** (not
  append) into per-school FAISS index; per-photo failures isolated (`ENROLLED`/`NO_FACE`/`MULTIPLE_FACES`/`ERROR`).
  Edge case: if **all** photos fail, old vectors are kept but stored URIs are replaced → possible divergence. No
  blur/pose/quality gating.
- **Inference (images + video):** video is **fully implemented** — fixed-FPS frame extraction (decord/opencv), per-
  frame detect→embed→search→decide, millisecond timestamps. Decision (locked): threshold filter → top-K=2 → gap:
  0 above = unknown (logged, no record); 1 = emit; 2 = emit top-1 alone if gap>threshold else **both with
  `needs_review=true`**. Dedupe best per `(student_id, media_id)` (two-layer idempotency).
- **`needs_review` + detection audit:** the ambiguity flag now drives a **human-in-the-loop** (BP5, decisions/0042):
  a backend `match_corrections` overlay (confirm/reject/add) consumed by galleries + download + notifications + the
  dashboard. **Still dark:** the **rich per-frame/per-face audit** (`media_detections`/`media_frames`/
  `face_detections`/`face_detection_candidates` + the `student_media_appearances` view) — only the dev test UI renders
  it — and there's **no ML feedback loop** (corrections are a backend overlay; the ML model/thresholds are untouched).
- **Multi-tenancy/scale:** strict per-school isolation; `IndexFlatIP` exact search (~≤50k students/school); LRU cache
  ~32 schools/worker; **single-replica enrollment serializes writes fleet-wide** (SPOF/bottleneck; Redis-lock
  Option B documented, not built). Model-version mismatch on read = fail loud.
- **Reproducibility:** every match stamps embedding/detector versions + thresholds used. No feedback/retraining/A-B.

---

## 8. Design system as-built (frontend)

**Tokens (`app/globals.css` `@theme`, light-only, dark-ready via CSS vars):** canvas `#fff` · surface `#f8f9fa` /
`-2 #f0f2f7` · hairline `#e3e8ef`/-strong; ink `#0d1729` / secondary `#5a6578` / muted `#8890a0`; **accent
`#6366f1`** / hover `#4f46e5`; semantic success/warning/error/info (+ `-soft`/`-strong`). Type: Geist Sans/Mono;
display-xl 48 / -lg 32 / -md 24 (negative tracking), headline 20, body 14, body-sm 12, tabular 13 (`tnum`). Radius
button 8 / card 12 / modal 16; hairline borders; 2px accent focus ring.

**Primitives (`components/ui/`):** button · input · textarea · field · card · dialog · confirm-dialog · tabs · table
· avatar · breadcrumb · toast · status-pill · progress-bar · spinner · skeleton · file-dropzone ·
multi-file-dropzone · page-header · empty-state · full-page-{error,message} · app-shell.
**Gallery (`components/gallery/`):** photo-grid · photo-tile · signed-image · lightbox · appearance-list ·
grid-skeleton · filter-chips.

**As-built observation (matters for the review):** the app executes **one of its three design references well
(Linear** — minimal, hairline, dense, indigo) but **under-delivers the other two**: **Pinterest** (photography-
forward masonry where the *image is the hero*; current grid is tight/square-cropped/plain) and **Stripe** (tabular-
numeral data richness, metrics, dashboards; current tables are thin + count-free). That mechanical gap is a big part
of "functional but not a great product."

---

## 9. What the product deliberately doesn't do yet (deferrals)

**Distribution/engagement:** notifications (email/push/SMS), announcements, "new since last visit", share links,
bulk export, download-all. **Experience/data:** dashboards with real stats, search/filter/sort, bulk actions, the
reference-photo thumbnail, video UI. *(needs-review triage + review/confirm/correct + report-a-miss **shipped** in
BP5, decisions/0042; **video render/upload/play/download shipped** in BP6, decisions/0043 — only the per-frame
timeline UI stays deferred.)* **Trust/accuracy (still deferred):** threshold-tuning UI, an **ML feedback loop** (corrections
are a backend overlay only), reference-photo quality gating. **Onboarding/business:**
self-serve school signup, CSV student import, plans/tiers/billing, per-school analytics. **Ops/scale:** multi-replica
enrollment (Redis lock), rate limiting, retention/erasure policy, access audit log, OTel tracing, security headers,
image thumbnails/derivatives, batch signed-URL minting. **Model:** re-enrollment cadence for growing children,
unknown-face handling. **Out of scope (owned by legal/contracts):** consent capture, parental consent, compliance
(COPPA/GDPR/DPDP). **UI polish:** dark-mode toggle.

_Live smoke of the FE↔Supabase↔ML path across F2–F6 remains unrun (Docker down during the build) — highest value is
the real `matches` + signed-download path._
