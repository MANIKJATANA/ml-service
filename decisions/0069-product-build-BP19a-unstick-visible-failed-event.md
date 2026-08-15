# 0069 — Product Build BP19a: Unstick + visible "Failed" event

- **Date:** 2026-08-09
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the first slice of **BP19 (Pipeline resilience & stall visibility)** — the fix for Round-3 **Critical
  #2** ([0064](0064-product-review-round-3-ux.md), theme K, finding R3-S1-01). Owner-approved slicing: **19a**
  unstick + visible failed event (this) · **19b** failure metrics · **19c** stall/second-batch/failed-in-dashboard
  visibility · **19d** upload survival. **The one BP19 migration (`0018`).**

## Context

A processing job that permanently fails — an `EmbeddingVersionMismatch` nacks every delivery (the index is stale
vs the configured embedder), or the job is otherwise exhausted — is retried 5× by the queue's `XAUTOCLAIM` and then
**dead-lettered to a Redis stream with no consumer anywhere**. The event is left `processing_status='processing'`
forever: the UI spins "Distribution is running — this updates automatically", the Process button is hidden while
in-flight, and the API refuses re-enqueue ("event is already queued or processing"). **No route, CLI, or ML path
ever resets it — only out-of-band SQL.** Students never get their photos; staff has no lever and no signal. Events
had **no `failed` state** (only media did, from BP8a).

## Decision

Mirror BP8a ([0049], which gave *media* a `failed` state + retry), applied to *events*. **Cross-service (backend +
ML worker); migration `0018`; no BE↔ML HTTP-contract change** (the worker already writes the backend status columns
directly, [0027]).

### 1. A `failed` event state (migration `0018`)
`EventProcessingStatus` gains `FAILED`; migration `0018` widens `ck_events_processing_status` from
`('not_started','queued','processing','completed')` to add `'failed'` (mirror of `0009`). Because the **ML worker
writes the value**, `0018` **must apply before the worker deploys** (documented in the migration). Reversible only
while no event is `failed` (the down re-imposes the 4-value CHECK).

### 2. The DLQ consumer that was missing (ML worker)
`BackendEventStore.mark_event_failed(school_id, event_id)` writes `failed` (no `completed_at`), tenant-scoped like
every write. The `JobQueue` port gains **`drain_dead_letters() -> list[DeadLetter]`** (reads the DLQ via `XRANGE`,
drops a malformed entry in place — it names no event — and returns the actionable ones **without** removing them)
+ **`remove_dead_letter(receipt)`**. `WorkerRunner.run()` now runs the consume loop AND a **`_dlq_loop`**
concurrently (`asyncio.TaskGroup`); each sweep marks every dead-lettered event `failed`
(`InferenceService.mark_event_failed`) **then** removes the entry — **mark-before-remove**, so a crash between the
two just re-marks idempotently on the next drain (the failure is never lost). Every loop swallows its own per-item
errors, so a bad job / DLQ hiccup never kills the worker.

### 3. The unstick guard + the stuck-too-long fallback (backend)
`EventService.process_event`'s in-flight guard is widened: Process is refused only when the event is `queued`/
`processing` **and** was enqueued recently (within `BE_EVENT_INFLIGHT_STALE_S`, default 30 min, compared to
`enqueued_at`). So a **`failed`** event re-enqueues (the "Retry" path — the DLQ consumer's primary unstick) **and**
an event stuck in-flight past the threshold re-enqueues (the fallback for a job that dead-lettered without a
consumer, or was lost with the stream) — no out-of-band SQL is ever needed. The BP8a `pending + failed == 0`
refuse stays (a `failed` event's media are still `pending`, so it re-processes). A missing `enqueued_at` on an
in-flight event (anomalous) counts as stale, so it can never be permanently un-retryable.

### 4. The frontend surfaces it
The event detail renders a `Failed` pill (tone `error`) — the count-recompute never overrides `failed` (its media
stay `pending`, which would misread as "not started") — a **Retry** button (`process_event` now allows it), and a
clear failure note in the existing `aria-live` region. `use-event-status` treats `failed` as terminal (not in
`IN_FLIGHT` → polling stops). The events list inherits the `failed` pill via the shared label/tone map.

## Why

- **Mark-before-remove over a consumer-group-on-the-DLQ:** the durable record of a failure is the event's `failed`
  status, and `mark_event_failed` is idempotent — so reading (not acking) the DLQ and removing only after marking
  is crash-safe with far less machinery than a second consumer group + `XAUTOCLAIM` on the DLQ. Marking
  at-dead-letter-time (a queue callback) was rejected: it has a crash window (entry acked off the main stream +
  DLQ'd but not marked → stranded) that the drain-with-persistent-DLQ design closes.
- **Both auto-`failed` AND a stale-threshold fallback** (owner's call): the DLQ consumer covers the common case
  promptly; the age threshold covers a truly-lost job that never reached the DLQ — together they guarantee an
  event can never strand, with no SQL.

## Consequences / honest limits (documented)

- **Migration `0018` must precede the worker deploy** (the worker writes `failed`). No ML-contract break; no new
  dependency; no new permission.
- **The DLQ drain is periodic** (`WorkerRunner` default 30 s): a dead-lettered event flips to `failed` within
  ~that interval, not instantly.
- **A malformed DLQ entry is dropped in place** (it names no event, so there's nothing to mark) — it was already
  logged as `malformed` when dead-lettered.
- **Multi-replica workers each run a DLQ loop** → redundant but harmless marks/removes (`mark_event_failed` +
  `XDEL` are idempotent); a DLQ consumer-group would de-dup but isn't worth the complexity for a near-empty stream.
- **`mark_event_failed` only flips a NON-terminal event** (`processing_status IN (queued, processing, failed)`):
  a crash between mark-and-remove can leave a stale dead-letter entry that is re-drained *after* the operator
  retried; without this guard the re-mark would clobber a now-`completed` event back to `failed` and re-strand it
  (a review-caught correctness fix). **Residual (documented):** if the retry is still in flight (`queued`/
  `processing`) when a surviving stale entry is re-drained, the event can *transiently* flap to `failed` — rare
  (needs a crash in the mark→remove micro-window + a retry before the worker restarts), self-correcting (the retry
  job drives it back to `completed`); a manual refresh clears the pill since polling stops on `failed`.
- **The DLQ read is bounded** at 256 entries per sweep (`_DLQ_DRAIN_MAX`) so a mass dead-letter can't balloon one
  sweep; any overflow drains on the next sweep.
- **The stuck-too-long fallback may re-enqueue a job that is actually still running** (past the threshold but not
  dead) — safe: per-photo writes are idempotent (NFR-5, `media_detections` replace-by-media, `matches`
  higher-confidence-wins), and the roster-skip is `== completed`, so a re-run just re-does outstanding photos.
- **Out of scope (per `product/07`):** orphaned-object reaping for event media (a known small leak — noted here,
  not a numbered finding); the failure *metrics* are **BP19b**; the age cue + second-batch + failed-in-dashboard
  are **BP19c**.
- Verified: migration `0018` **up→down→up on a throwaway Postgres** (`bp19_migtest`, dropped; dev `app` untouched —
  the CHECK confirmed to accept `failed` + reject a bogus value; the down correctly refuses while a `failed` row
  exists). BE ruff+mypy+**586 passed / 39 skipped** + layering (guard tests: fresh-in-flight refused,
  stale-in-flight retryable, `failed` retryable incl. the all-photos-completed self-heal). ML ruff+mypy+**139
  passed / 13 skipped** + layering (DLQ tests: marks-then-removes with strict order, empty-drain no-op) + **gated
  real-Postgres** `mark_event_failed` (idempotent + tenant-scoped + the no-clobber-of-`completed` guard) **and a
  gated real-Redis** `drain_dead_letters`/`remove_dead_letter`/malformed-drop round-trip. FE lint+tsc+`next build`
  green.
- **2× review loop — both SHIP:** **R1** (correctness/security/tenant/async) caught a **real crash-window bug** —
  a stale dead-letter re-drained after a retry could clobber a `completed` event back to `failed` and re-strand it;
  fixed with the state-guarded `mark_event_failed` (never flips a terminal event) + a gated no-clobber test.
  Everything else (mark-before-remove crash-safety, the stale-window math + tz handling, tenant scope, TaskGroup
  concurrency, the version-mismatch-doesn't-premark path, the migration contract) verified clean. **R2**
  (edges/coverage/a11y) — SHIP → closed the `failed`-with-no-outstanding-media **Retry dead-end** (the guard now
  lets a `failed` event always retry + self-heal, + the FE button shows for a `failed` event), added the **gated
  real-Redis** DLQ test (the only untested new logic), promoted the DLQ poll interval to a setting
  (`ML_DLQ_POLL_S`), bounded the DLQ read (256/sweep), and fixed the "contact support" copy. a11y (error-tone
  contrast, single-note, `aria-live`) confirmed AA.
- **Next:** BP19b (failure metrics — the worker gets a `/metrics` endpoint + `jobs_failed_total`/`dlq_depth`/
  `in_flight_age`/`photos_failed_total`).
