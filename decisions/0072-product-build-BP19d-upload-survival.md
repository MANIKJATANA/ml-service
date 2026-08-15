# 0072 — Product Build BP19d: Upload survival

- **Date:** 2026-08-09
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the fourth and **final** slice of **BP19 (Pipeline resilience & stall visibility)** — after 19a unstick
  ([0069](0069-product-build-BP19a-unstick-visible-failed-event.md)), 19b metrics
  ([0070](0070-product-build-BP19b-failure-metrics.md)), 19c visibility
  ([0071](0071-product-build-BP19c-stall-second-batch-failed-visibility.md)). Redeems Round-3 findings
  **R3-A2-09 / R3-A3-06 / R3-S3-05**. **FE-only — no backend/ML change, no migration, no new dependency, no new
  permission. Completes BP19 → Round-3 Critical #2 is fully closed.**

## Context

The event photo uploader (`useMediaUpload` + the upload page) had two survival gaps: a file that failed mid-batch
was isolated in an `error` state with **no way to retry** except re-picking every file, and there was **no guard
at all** against losing an in-progress upload — a stray tab-close, reload, or click-away just abandoned it (the FE
had **zero** `beforeunload` handlers anywhere).

## Decision

- **Retry failed uploads.** `useMediaUpload` now retains each file's **`File` handle** by item id
  (`useRef<Map<id, File>>` — `File` objects are cheap references, not the bytes, and the map dies with the page).
  The bounded-concurrency pool is extracted to a `runPool(entries)` shared by `add` and a new **`retryFailed()`**,
  which collects the `error` items' retained files, resets them to `queued`, and re-runs the pool over **only**
  those — no re-picking. A **"Retry failed (N)"** button appears when `failed > 0 && !isUploading` (so no
  overlapping pools race the same item).
- **A reusable interruption guard.** New **`useBeforeUnload(active)`** (`lib/hooks/use-before-unload.ts`) adds a
  `beforeunload` listener while `active`, warning before a **tab-close / reload / external-URL** navigation; wired
  as `useBeforeUnload(isUploading)` on the upload page.
- **A nav-confirm instead of a trap.** The "Back to event" button was `disabled` during an upload (trapping the
  user); it's now enabled and routes through `onBack()`, which opens a `ConfirmDialog` ("Leave while uploading?")
  when `isUploading` — so the user can leave deliberately but not by accident.

## Why

- **Retain `File` handles over re-picking:** the failure the finding names is a *flaky/interrupted* upload; the
  file the user already chose is still valid, so keeping the handle and re-running just the failures is the
  minimal, correct recovery (mirrors the students bulk-photo "Retry failed").
- **`beforeunload` for the external vectors + an explicit confirm for the in-app Back:** these are the two
  data-loss paths a hook can actually intercept. In-app *router* navigation is confirmed on the control that
  triggers it, because Next 16's App Router has no stable navigation-blocking API (see honest limits).

## Consequences / honest limits (documented)

- **FE-only; no backend/ML/dep/permission/migration change.**
- **In-app breadcrumb / browser-Back navigation is NOT guarded.** `beforeunload` doesn't fire for client-side
  router navigation, and Next 16 App Router exposes no stable in-app nav-blocking hook — so a mid-upload click on
  a Breadcrumb link or the browser Back button still leaves silently. The covered vectors (tab-close/reload/
  external + the explicit "Back to event" confirm) are the common ones; the breadcrumb/back gap is a documented
  Next-App-Router constraint, not an oversight.
- **Leaving via in-app nav does not abort the uploads.** The pool is a **detached** `Promise.all`, so after the
  page unmounts its workers keep pulling from the batch and **all** files (in-flight *and* still-queued) finish
  uploading server-side — the `mounted` ref only no-ops the (now-gone) UI patches. So an in-app "Back" costs
  *progress visibility + retry*, not photos. A **tab-close / reload** is different — it destroys the JS context and
  DOES kill the pending uploads, which is exactly the vector `useBeforeUnload` guards. The confirm copy reflects
  this ("they'll keep uploading in the background… closing the tab would stop them").
- **The retained-`File` map is append-only.** `filesById` is never pruned on success (so a retry-after-success
  stays possible), so a long session with many large batches keeps every handle until the page unmounts — bounded
  and acceptable (`File`s are references, not bytes; the map dies with the page).
- **`useBeforeUnload`'s prompt text can't be customized** — modern browsers show a generic "Leave site?" dialog;
  setting `returnValue` only triggers it (documented in the hook).
- **Reusable follow-on:** `useBeforeUnload` is generic — the same guard fits the other long-ops the plan named
  (`useBulkPhotoEnroll`, `useDownloadAll`); applying it there is a small follow-up, not in this slice.
- Verified: FE **lint + tsc + `next build` green**. No backend/ML change (no BE/ML suite delta). **2× review loop —
  both SHIP, no code blockers.** **R1** (correctness/async/races) verified all six areas: the single-pool invariant
  (the "Retry failed" button gates on `!isUploading`, and each `runPool` has its own `idx`), unmount-safety via the
  `mounted` ref, the `beforeunload` hook textbook-correct (deps + cleanup), and clean types — 0 fixes. **R2**
  (edges/a11y/honesty) — SHIP → wrote this doc's honest limits, and **corrected the confirm copy**: investigating
  it revealed the pool is a *detached* `Promise.all` (workers keep running after in-app unmount), so an in-app
  "Back" loses visibility/retry but not photos (only a tab-close kills them) — the copy now says "they'll keep
  uploading in the background… closing the tab would stop them" instead of implying loss. Added the append-only-map
  invariant comment (R1 NIT). a11y confirmed sound (Radix ConfirmDialog focus-trap/labelled; the `aria-live` status
  line announces retry completion; the Retry button has a text accessible name).
- **BP19 (Pipeline resilience & stall visibility) is now complete (a, b, c, d) — Round-3 Critical #2 is fully
  closed.** Next: the owner picks the next Round-3 phase (the recommended order continues BP21 → BP20 → …).
