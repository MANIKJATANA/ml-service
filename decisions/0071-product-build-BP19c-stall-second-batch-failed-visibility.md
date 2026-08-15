# 0071 — Product Build BP19c: Stall + second-batch + failed-in-dashboard visibility

- **Date:** 2026-08-09
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the third slice of **BP19 (Pipeline resilience & stall visibility)** — after BP19a's unstick
  ([0069](0069-product-build-BP19a-unstick-visible-failed-event.md)) + BP19b's metrics
  ([0070](0070-product-build-BP19b-failure-metrics.md)). The **display half** of theme K — redeems findings
  **R3-S1-03** (a stuck event looks healthy), **R3-S1-04** (the second batch is invisible), **R3-S1-10** ("All
  processed" over failed photos). **BE + FE; no migration, no ML change.**

## Context

19a/19b made the pipeline *recoverable* and *measurable*; 19c makes its state *visible* to staff. Three gaps: a
stuck event was indistinguishable from a healthy one (the eternal "Distribution is running — this updates
automatically", `enqueued_at` delivered to the FE but rendered nowhere); new photos on an already-`completed`
event (a "second batch") went unnoticed — the events-list pill read a stale "Completed" and the dashboard alert
only caught never-processed events; and the dashboard said "All processed" even when photos had `failed`.

## Decision

### 1. Staleness cue (R3-S1-03, FE-only)
The event detail replaces "Distribution is running — this updates automatically" with **"Processing since
{enqueued_at}"** (the age was already delivered) and, once in-flight past the threshold, escalates ("This is
taking longer than usual; you can retry below.") and **surfaces the Retry** (19a's widened guard allows a
stale-in-flight re-enqueue). The threshold is a FE mirror **`NEXT_PUBLIC_EVENT_INFLIGHT_STALE_S`** (default 1800,
mirroring `BE_EVENT_INFLIGHT_STALE_S`); "now" is tracked in an effect (a lazy-`useState(() => Date.now())` +
30s-interval while in-flight) — never read impurely in render — so the escalation appears as the threshold is
crossed.

### 2. The second batch (R3-S1-04, BE + FE)
- **The list pill derives from counts, not the raw status.** A new pure **`derivePillStatus(processing_status,
  {total, pending})`** in `lib/events/status.ts` — shared by the event **detail** (refactored to it) and the
  events **list** — so a `completed` event with new `pending` photos reads *unfinished*, not "Completed". The list
  row carries the new count: `MediaRepository.pending_counts_by_event` (one grouped scan) → `EventListing.pending`
  → `EventListItem.pending` (threaded through both the row-native and count-sort paths of `list_events_page`).
- **The dashboard alert is widened.** `EventRepository.count_not_started_with_media` → **`count_active_with_
  pending_media`**: active, **not-in-flight** events with **≥1 `pending` photo** (was: `processing_status ==
  not_started` + any media). So a second batch on a `completed` (or `failed`) event now fires the "photos to
  process" alert; in-flight and archived events stay excluded.

### 3. Failed photos in the dashboard (R3-S1-10, BE + FE)
`school_status_counts` already counts `failed`; expose it — `SchoolDashboard.photos_failed` →
`MediaSummary.failed` + a `NeedsAttention.photos_failed`. The FE `photosHint` stops saying "All processed" when
`pending > 0 || failed > 0` (shows "N awaiting processing · N failed"), and a new **"N photos failed processing"**
needs-attention alert links to events.

## Why

- **A shared `derivePillStatus`** guarantees the list and detail agree (the finding was that they *diverged*), and
  keys the "second batch" on **`pending`** (not `pending + failed`) so a `completed`-with-failed-photos event still
  reads "Completed" (BP8a's deliberate event-level semantics) while a `completed`-with-new-uploads event reads
  unfinished.
- **Widening keys on `pending` media, not the event status** — the only signal that survives a re-upload onto a
  finished event.

## Consequences / honest limits (documented)

- **No migration, no ML change, no new dependency, no new permission.** One breaking-ish read shape: `EventListItem`
  gains `pending`, `DashboardResponse.media` gains `failed`, `needs_attention` gains `photos_failed` — additive,
  shipped WITH the FE.
- **The FE stale threshold is a `NEXT_PUBLIC_*` mirror** of the backend guard (like BP10's bulk-photo cap) — keep it
  `>=` the backend value so the FE never offers a retry the backend would 400; a drift only shifts the escalation
  timing (documented in `.env.example`).
- **The list pill is derived, but the events-list `events_undistributed`-style dashboard chip counts stay the BP2
  raw rollup** — galleries/detail remain the effective source of truth (consistent with the BP5 divergence note).
- **The "distribute" vocabulary is untouched** — the dashboard alert keeps its BP4-era wording; the R3 one-grammar
  cleanup is a separate phase (BP21), so 19c widened the *predicate* without renaming the field.
- Verified: BE ruff+mypy+**590 passed / 39 skipped** + layering (dashboard: second-batch widening + `photos_failed`
  + not-in-flight/archived exclusions incl. an explicit in-flight-not-flagged guard; listing: `pending` carried + a
  second-batch case) + a **gated real-Postgres** round-trip for `count_active_with_pending_media` (the e6
  completed-with-second-batch case) + `pending_counts_by_event` (throwaway `bp19c_test`, dropped; dev `app`
  untouched). FE lint+tsc+`next build` green.
- **2× review loop — both SHIP, no blockers.** **R1** (correctness/tenant/async) traced all seven areas correct —
  the widened SQL predicate tenant-scoped on both sides + NULL-safe, `pending` threaded through both list paths,
  `derivePillStatus` a faithful extraction of the detail page's prior logic (keys on `pending`, so BP8a's
  completed-with-failed-photos "Completed" survives), the impure-render fix respects the Rules of Hooks, and the
  FE/BE stale thresholds are contract-consistent (FE `>=` BE, graceful toast on drift). **R2** (edges/coverage/a11y)
  — SHIP → **fixed the widened alert's now-false copy** ("…haven't been sent to students yet" → "with photos to
  process" / "haven't been processed yet") and **added a service test** that an in-flight event with pending media
  is NOT flagged (guarding the fake's in-flight skip). The pre-existing "Not started" label for a second batch is a
  faithful port (a vocab call deferred to BP21, not a 19c regression); a11y contrast + `aria-live` announcement
  confirmed.
- **Next:** BP19d (upload survival — Retry failed + a beforeunload guard; FE-only).
