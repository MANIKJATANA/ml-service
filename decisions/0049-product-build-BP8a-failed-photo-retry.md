# 0049 — Product Build BP8a: Failed-photo state + retry

**Date:** 2026-07-16
**Status:** Accepted

## Context

The first slice of **BP8 (Ops & reliability)** — the roadmap's final, ops-focused phase (`product/03`, Impact M / risk
reduction). Grounded in a current-state exploration, BP8 splits into five independent slices: **BP8a** failed-photo state
+ retry · **BP8b** access/download audit · **BP8c** rate limiting (+ security headers) · **BP8d** multi-replica
enrollment (Redis-lock Option B) · **BP8e** retention/erasure. Owner picked **BP8a first** (the only strongly
*user-visible* one). Fails **X3/T7**: today a photo the ML worker can't process is **silently skipped** and looks
`pending` **forever** — indistinguishable from "still processing", with no retry. **Backend + ML worker + FE; one
migration (`0009`); no ML-contract break.**

## Decisions

### 1. A `failed` media state (migration `0009`)
`MediaProcessingStatus` gains `FAILED`; migration `0009` widens `ck_media_processing_status` from
`('pending','completed')` to add `'failed'`. Because the **ML worker writes the value** (into the backend-owned `media`
table via its mirror), `0009` **must be applied before the worker change deploys** (documented in the migration).
Reversible only while no `failed` row exists (down re-imposes the 2-value CHECK) — documented, like `0008`.

### 2. The worker marks a photo it can't process `failed` — visible **and** retryable
`InferenceService.process_event`'s per-photo loop now calls a new `BackendEventStore.mark_media_failed` (writes
`failed`, **no `completed_at`**) on a `MediaFetchError` / `MediaDecodeError` / any other per-photo exception — instead of
silently skipping. The systemic **`EmbeddingVersionMismatch` still aborts the whole event** (nack + alert) and marks
**nothing** failed (the *index* is wrong, not the photo). The event still reaches `completed` even with failures — the
"done, N failed" signal. `EventOutcome` splits `photos_skipped` (now only already-`completed`) from `photos_failed`.

### 3. Retry = redistribute (the worker re-attempts non-`completed` photos)
The worker's roster skip stays **`== completed` only**, so a `failed` photo is **re-attempted** on the next Process.
Crucially, the backend's **`process_event` enqueue guard was widened**: it refuses only when
`pending + failed == 0` (was `pending == 0`) — otherwise a `failed`-only event's "Retry failed" would 400 (the core
promise). `EventStatusResponse` gains `failed` (+ `total = pending + completed + failed`).

### 4. Frontend surfaces it
The event detail shows `· N failed` in the counts, a **warning note** (in the existing `aria-live` region) framing
retry as the primary action ("Retry — if it keeps failing, the file may be corrupt or unreadable, so replace it" — since
a *transient* fetch blip is also marked failed), and the Process button now shows when `pending > 0 || failed > 0`
(labelled **"Retry failed"** when only failures remain, else "Process"/"Redistribute"). "All photos processed" is gated
on `failed === 0`.

## Honest limits (documented)

- **Every per-photo failure is marked `failed`, transient or permanent.** A storage blip and a corrupt file both land
  `failed`; the copy leads with "Retry" so a transient one self-heals on the next Process, and only calls out
  "corrupt/unreadable → replace" as the if-it-persists fallback.
- **The event pill still reads "Completed" when `failed > 0`** — it's the *event-level* processing status (processing did
  finish); the per-photo failures are the failed count + warning note, deliberately separate. (Reviewer nit, accepted.)

## Verification

- BE gate green: ruff + mypy + **full suite 346 passed / 23 skipped** — incl. the widened `process_event` guard
  (`test_process_retries_a_failed_only_event`), the status body carrying `failed`, and a **gated real-Postgres**
  `mark_media_failed` round-trip through the widened CHECK. **Migration `0009` verified up→down→up on a throwaway
  Postgres** (`bp8a_test`, dropped; dev `app` DB untouched) with the CHECK confirmed to include `failed`.
- ML gate green: ruff + mypy + **128 passed / 7 skipped** — fetch-error→failed, a `failed` photo **retried** on
  redistribute, the version-mismatch marks **nothing** failed, and the generic-exception path marks failed + finalizes.
- FE gate green: `tsc --noEmit` + `eslint` + `next build`.
- **2× review→fix loop** (two agents). **R1 caught a BLOCKER** I'd missed — the `process_event` enqueue guard still
  rejected `pending == 0`, so the FE's "Retry failed" would 400; fixed + tested. Everything else (retry skip condition,
  version-mismatch abort, migration/CHECK contract, event finalization, the outcome split, KeyError-safety) verified
  clean. **R2** → softened the transient-failure copy + added the two test guards (version-mismatch-marks-nothing-failed;
  generic-exception path); a11y contrast/announce + edge cases confirmed correct.

## Follow-ups

**BP8b–e** (per `product/03` / this doc's Context): access/download audit, rate limiting (+ security headers),
multi-replica enrollment (Redis-lock Option B), retention/erasure. Optional BP8a polish: a distinct pill tone for
completed-with-failures; a `media_failed` Prometheus counter.
