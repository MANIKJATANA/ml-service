# 05 — Parked / skipped backlog (the "what we consciously didn't build" tracker)

> **This file = the single record of everything deliberately parked or skipped.** Nothing here is being
> worked on. Each item is picked up **only on an explicit owner request** — and when it is, re-confirm scope
> first (the note + its source decision hold the context). This exists so a future instance (or owner) can see
> *what was skipped and why* at a glance, instead of re-deriving it from the roadmaps + decisions.
>
> _Snapshot: 2026-07-27. The recommended tracks are done: **BP1–BP8** (`03`) and the **BP9–BP14 + BP17**
> recommended Round-2 track (`04`) have all landed. What remains is only what's listed below — all parked._
> See [decisions/0063](../decisions/0063-park-remaining-backlog.md) for the parking decision.

---

## A. Parked phases (deprioritised → back of queue, owner calls)

Fully specced in `04-improvement-roadmap-round-2.md`; re-confirm scope when picked up.

| Phase | What | Why parked | Source |
|---|---|---|---|
| **BP12** — Distribution reach | Outbound **email** (to the student-account address) + a tokenized **share link**, dropped into BP4's `CompositeNotifier` seam | Still a **Critical** finding (in-app-only delivery); parked on **effort/infra** — needs the first outbound-notification provider + templates, not importance | [`04` §BP12](04-improvement-roadmap-round-2.md), [0041](../decisions/0041-product-build-BP4-distribution.md) |
| **BP15** — Accuracy at scale | Enrollment **staleness** signal + re-enroll prompt; per-event **expected-vs-matched reconciliation** ("18 of 22 enrolled found — who's missing?") | Deprioritised; **cohort-scoped matching** (grade-narrowed ML index) already **dropped** by owner (brings it M→ from M–L) | [`04` §BP15](04-improvement-roadmap-round-2.md) |
| **BP16** — Lifecycle & retention | Bulk archive (partly shipped in BP13); **event hard-delete** (purge media rows + storage objects + matches/detections, reusing BP8e's erasure machinery); optional **time-based retention** | Pure risk-reduction — lowest product urgency; safe at the back until the flat lists actually clutter | [`04` §BP16](04-improvement-roadmap-round-2.md), [0053](../decisions/0053-product-build-BP8e-student-erasure.md) |

**Folds into BP16 (so parked with it):** event hard-delete + time-based retention (both deferred from
[BP8e / 0053](../decisions/0053-product-build-BP8e-student-erasure.md)).

## B. Parked features (deferred from a landed phase)

| Feature | What | Why parked | Source |
|---|---|---|---|
| **BP6 video timeline** — "who appears when" | A per-timestamp timeline of which student appears at which moment in a video: a new isolated `student_media_appearances` read + `GET /media/{id}/timeline`, BP5-corrections-overlaid | Owner call (2026-07-27): **skip it.** BP6 shipped video core (upload/render/play + grid poster); the timeline is the one part needing a net-new backend read | [0043](../decisions/0043-product-build-BP6-video-end-to-end.md) |

## C. Scale-up / polish refinements (documented "honest limits" — not phases)

Each is a known trade-off recorded in its phase's decision. Do **only** if a real need arises; none is a
planned build.

- **Pagination:** offset paging everywhere → **keyset** is the scale-up ([0055](../decisions/0055-product-build-BP9-scale-ready-lists-galleries.md), BP9).
- **Analytics trends:** query-only (derived from timestamps) → a **snapshot table + rollup job** for true
  historical lines ("enrolled over time") ([0062](../decisions/0062-product-build-BP14-program-analytics.md), BP14).
- **Thumbnails:** synchronous backend generate-on-upload → **async** generation ([0056](../decisions/0056-product-build-BP17-image-thumbnails.md), BP17).
- **Rate limiting:** fixed-window (2× burst at a boundary) → **sliding-window**; the FE keeps `'unsafe-inline'`
  CSP → a **nonce-strict CSP via `proxy.ts`** ([0051](../decisions/0051-product-build-BP8c-rate-limiting-security-headers.md), BP8c).
- **FAISS write lock:** the Redis TTL lock has no **lease auto-extension** (a write slower than the lease
  auto-expires — loudly logged) ([0052](../decisions/0052-product-build-BP8d-multi-replica-enrollment.md), BP8d).
- **Observability:** **OTel tracing** at the service boundary is opt-in/deferred ([0029](../decisions/0029-hardening.md)/[0037](../decisions/0037-frontend-polish-and-hardening.md)).
- **FE polish:** dark-mode toggle, per-page `aria-busy` wrappers, a service-side error logger ([0037](../decisions/0037-frontend-polish-and-hardening.md), F7).

## D. Verification still pending (not features — need a running stack / Docker host)

- **FE live smoke (F2–F6):** the Supabase direct-upload contract + the count-rich list/gallery/distribution
  flows have passed the gate (tsc + lint + build) but not a **live run against a running stack**.
- **ML runtime path:** the Docker image build + **`buffalo_l` bake** + the **InsightFace** enroll/inference
  runtime execute in CI's `docker-build` job / on a Docker host — **not yet run on this dev machine**.

---

## How to use this file

- **Nothing here is scheduled.** Picking any item up needs an explicit owner request + a scope re-confirm.
- When an item **is** built, remove it here and tick its home roadmap (`03`/`04`) — keep this file to only what
  is *still* parked.
- When a **new** deferral is made in any phase, add it here in the same change (so this stays the one true
  "what's parked" list).
