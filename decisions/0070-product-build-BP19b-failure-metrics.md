# 0070 — Product Build BP19b: Failure metrics

- **Date:** 2026-08-09
- **Status:** implemented (gate green; awaiting owner review before commit)
- **Phase:** the second slice of **BP19 (Pipeline resilience & stall visibility)** — after BP19a's unstick + visible
  failed event ([0069](0069-product-build-BP19a-unstick-visible-failed-event.md)). Redeems Round-3 finding
  **R3-S1-02** ([0064](0064-product-review-round-3-ux.md), theme K). **ML-service only — no migration, no backend/
  frontend change, no ML-contract change.**

## Context

The failure half of the pipeline emitted **zero metrics**: job metrics fired only on the ack (success) path;
nacks and dead-letters were log lines with no counter, `photos_failed` was computed on every event and **never
exported**, and there was no DLQ-depth or in-flight-age gauge — so the "ALERT" log line (a stale index) had
nothing to fire an alert. Worse, exploration found **the inference worker has no `/metrics` HTTP server at all** —
only the ML *API* (a separate process) serves `/metrics`, so even the worker's existing job-outcome counters were
recorded into a registry nobody scraped.

## Decision

Give the worker a scrape endpoint and add the failure metrics.

- **The worker serves `/metrics`** (`observability/metrics.py::start_metrics_server` → `prometheus_client.
  start_http_server` on `ML_WORKER_METRICS_PORT`, default 9100; called in `workers/inference_worker.py::main` in a
  **fail-safe** `try/except OSError` so a port-in-use logs + continues — metrics are not core). It exposes the
  **default registry**, so the worker's `/metrics` now serves BOTH the pre-existing job-outcome counters (finally
  scraped) AND the new failure metrics; the API keeps serving its own registry at `/metrics`.
- **New metrics** (`observability/metrics.py`, the same cardinality discipline — bounded labels only, never
  `student_id`/`media_id`):
  - `photos_failed_total` (counter, `_LABELS`) — folded into `record_job_outcome` from the already-computed
    `EventOutcome.photos_failed`.
  - `jobs_failed_total{reason}` (counter) — a terminally-failed (dead-lettered) job; incremented once per drained
    dead-letter in `runner._drain_dead_letters_once` with `reason` = the queue's cause (a small closed set).
  - `embedding_version_mismatch_total{school_id}` (counter) — the stale-index "ALERT", now countable; incremented
    in the runner's version-mismatch handler (an early signal — a rising rate means the index is stale, *before*
    the job dead-letters after 5 retries).
  - `dlq_depth` (gauge) + `inflight_oldest_age_ms` (gauge) — worker-observed queue health, refreshed each DLQ
    sweep (`runner._refresh_queue_gauges` → `set_queue_gauges`).
- **Queue stats via the port:** `JobQueue.dead_letter_depth()` (redis `XLEN` of the DLQ) + `oldest_pending_age_ms()`
  (redis `XPENDING` summary → oldest pending id → the `<ms>-<seq>` id's ms prefix → `now − ms`, clamped ≥ 0, `None`
  when nothing is pending); inproc stubs (0 / `None`).
- **Wiring:** `ML_WORKER_METRICS_PORT` in settings + `.env.example`; the compose `ml-worker` service exposes 9100.

## Why

- **Worker `/metrics` server over Redis-sync-to-the-API:** the metrics are worker-process facts (job outcomes,
  dead-letters, queue depth); a standard per-instance scrape endpoint (`start_http_server`) is the idiomatic
  Prometheus pattern and also redeems the pre-existing "worker metrics never scraped" gap in one move, with no new
  coupling. Fail-safe because an observability bind failure must never take down inference.
- **`version_mismatch` as its own counter** (not just a `jobs_failed` reason): a version mismatch is visible on the
  *first* failed delivery — a rising `embedding_version_mismatch_total` alerts in seconds, whereas the job only
  reaches `jobs_failed_total` after ~5 retries × the idle window (minutes).

## Consequences / honest limits (documented)

- **No migration, no backend/frontend change, no new dependency** (prometheus_client already present), no new
  permission, no ML-contract change.
- **The worker and API expose SEPARATE `/metrics`** (two scrape targets) — Prometheus must scrape both; they share
  metric *definitions* (default registry) but hold each process's own *values*.
- **Multi-replica workers each report the same shared `dlq_depth`** (they all see the one DLQ stream) — aggregate
  with `max()` across instances, not `sum()`; likewise give each worker on one host a distinct
  `ML_WORKER_METRICS_PORT` + host mapping (like `ML_QUEUE_CONSUMER`).
- **A metrics-server bind failure degrades silently to no-metrics** (logged WARNING) — the worker keeps processing.
- **`inflight_oldest_age_ms` is derived from the stream-id timestamp** (`now − id_ms`, clamped ≥ 0) — it assumes
  reasonable clock sync between the worker and Redis; a skew only nudges the gauge, never crashes.
- **`embedding_version_mismatch_total` counts delivery attempts, not distinct jobs** (it fires per nack, ~5× per
  stuck job) — that is the intended "rate of mismatches" alert signal, documented so it isn't misread as a
  distinct-job count.
- Verified: ML ruff+mypy+**145 passed / 14 skipped** + layering (observability tests: the failure counters +
  the `photos_failed` fold + the gauges + `render_latest` exposes the new names; **runner-wiring** tests: a
  version-mismatch increments the counter, a dead-letter increments `jobs_failed_total{reason}`, a sweep pushes
  the gauges) + a **gated real-Redis** `dead_letter_depth`/`oldest_pending_age_ms` round-trip (idle→`None`, a
  pending job has a measurable age). No backend/FE change.
- **2× review loop — both SHIP, no blockers.** **R1** (correctness/cardinality/async) confirmed the cardinal
  metrics rule holds (every label bounded), `oldest_pending_age_ms` sound (clamped, `None`-safe, `_ensure_group`
  before `XPENDING`), the fail-safe server + default-registry exposure correct, async clean → applied its one
  robustness NIT: the **DLQ drain now runs before the gauge refresh in its OWN `try`**, so a persistent
  gauge-read failure can never starve the drain (which is BP19a's core recovery). **R2** (edges/coverage/honesty)
  → added the **runner-wiring tests** (the load-bearing "does the runner actually increment these" gap), and the
  two doc/help-string NITs — the version-mismatch help now says "attempts" (it fires per delivery, ~5× per stuck
  event — a rate signal, not a distinct-job count) and both gauges' help notes "worker-observed; use `max()`" for
  the multi-replica shared-stream aggregation.
- **Next:** BP19c (stall + second-batch + failed-in-dashboard visibility — BE + FE).
