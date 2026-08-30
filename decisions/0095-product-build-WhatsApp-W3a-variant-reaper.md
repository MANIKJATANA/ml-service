# 0095 — WhatsApp W3a: variant-object cleanup (the reaper)

- **Date:** 2026-08-31
- **Status:** implemented (BE gate green; 2× review loop SHIP). **Committed + pushed.**
- **Scope:** the first slice of **W3** (the WhatsApp scale/reliability phase), following Phase 0
  ([0092](0092-product-build-WhatsApp-Phase0-student-mobile-optin.md)), W1
  ([0093](0093-product-build-WhatsApp-W1-provider-foundation.md)), W2
  ([0094](0094-product-build-WhatsApp-W2-send-flow.md)). W3a closes the W2 "honest limit" that
  the ≤5 MB send-variant objects are never reaped. **Backend-only; no migration, no ML change, no
  new dependency, no new permission, no worker.**

## Context

W2 uploads a ≤5 MB "send variant" of each photo to a deterministic object key
`{whatsapp_variant_prefix}/{school_id}/{media_id}.jpg` and mints a short-lived signed URL for it
(TTL `download_url_ttl_s`, default 1h). The variant object outlives that URL and was never deleted
— one small private JPEG accumulating per distinct media ever sent. W3a adds the cleanup.

W3's architect finding shaped the slicing: **the backend has no worker process** (it's a pure
FastAPI API — the only worker in the repo is the ML inference worker). So the flagship
"send-to-all-in-an-event" (W3c) needs genuinely new infrastructure. W3a was chosen first because
it is the only W3 slice with **zero live-Gupshup dependency, no new worker, and no PII surface** —
pure storage hygiene, fully fake-testable now.

## Decision

An **operator-run CLI reaper** (not a scheduled process — the backend has no scheduler):
`python -m backend.cli.reap_whatsapp_variants [--older-than-hours N] [--dry-run] [--school ID]`.

- **The reaper logic is a pure service** `services/whatsapp_variant_reaper.py::reap_whatsapp_variants`
  (imports only the `ObjectStore` port + stdlib + structlog + domain errors — layering-clean). It
  lists objects under the prefix (or `{prefix}/{school_id}`), keeps every object **younger than**
  the retention window, and deletes the rest **best-effort** (a per-object delete failure is
  counted and the run continues — the BP27/W2 pattern), returning a frozen `ReapSummary
  {scanned, deleted, skipped_recent, errors}`.
- **Safety by construction — the load-bearing invariant:** age-based only. It **never deletes an
  object younger than `retention`** (`keep if last_modified > now - retention`), so it cannot race
  a fresh send. The default retention (24h, `whatsapp_variant_retention_hours`) is **24× the 1h
  signed-URL TTL**, so a reaped variant is already unreachable and is re-created on the next send
  (the key is deterministic + overwritten). A **non-positive retention is refused** at two layers
  — the CLI's `--older-than-hours` argparse validator (fails before the container builds) **and** a
  defense-in-depth `ValueError` in the service (protects any future non-CLI caller) — since a `<=0`
  window would set the cutoff to now/the future and reap fresh, in-flight variants.
- **One port addition:** `ObjectStore.list_prefix(prefix) -> list[StoredObject]` (a new frozen
  `StoredObject {key, last_modified}` VO; all timestamps tz-aware UTC). Implemented in the
  **local_fs** adapter (recursive `rglob` + mtime — the fully-testable path; its `upload_bytes`/
  `download_bytes`/`delete` were promoted from no-op stubs to real filesystem ops so the round-trip
  is genuine — a dev-only change, prod uses supabase, and `download_bytes` still raises
  `UpstreamError` on a missing object, preserving the BP17/W2 contract), the **supabase** adapter
  (a two-level `.list()` walk prefix→school→files, tolerant timestamp parsing, unreadable timestamp
  → treated as recent/kept — conservative), and the **fake** (records per-key timestamps +
  test helpers).
- **Scheduling is operator-driven + documented:** a `docker-compose.yml` comment near the
  `backend` service gives the one-shot command (`docker compose run --rm backend python -m
  backend.cli.reap_whatsapp_variants`); the CLI/module docstrings + `.env.example` note the same.
  New setting `whatsapp_variant_retention_hours: int = 24` (+ `BE_WHATSAPP_VARIANT_RETENTION_HOURS`).

## Verification

- **Backend gate:** ruff + mypy (198 source files) + layering clean (the reaper service imports no
  IO lib — `structlog` is permitted in `services/`); **pytest 817 passed / 51 skipped**.
- **Tests:** the reaper decision path against the fake (reap-old/keep-recent, dry-run reports but
  deletes nothing, `--school` narrows to one school, best-effort delete-failure continues + the
  `deleted+skipped_recent+errors == scanned` invariant, empty prefix → clean zero, the exact-cutoff
  boundary is reaped, the default-`now` wall-clock keeps a fresh upload, **a `<=0` retention is
  refused**); the CLI guard (`_positive_hours` rejects `<=0`; `main(["--older-than-hours","0"])`
  exits 2 **before** the container is built — a monkeypatched `Container` proves the guard runs
  first); the local_fs `list_prefix`/byte round-trip + missing-prefix-empty.
- **No FE change, no migration, no ML change, no new dependency, no new permission, no worker.**
- **2× review loop:** **R1 (correctness/safety) — SHIP, 0 blockers**: the retention rule proven
  (a fresh send is never reaped; only objects ≥ retention old are deleted; tz-aware throughout),
  and the local_fs deviation proven backward-compatible (dev-only; prod = supabase; in-suite
  callers use the fake; the missing-object `UpstreamError` contract preserved + tested). **R2
  (edge/UX/docs) — SHIP, 4 should-fix + 2 nits applied**: the `--older-than-hours <=0` guard (both
  layers), a CLI guard smoke test, refreshing the now-stale W2 "not reaped" comment to point at the
  reaper, and this decision doc + the scheduling runbook (compose comment); plus the
  summary-consistency assertion and the documented supabase scale note.

## Honest limits (documented)

- **Operator-driven, not scheduled** — the backend has no scheduler; the reaper must be run on a
  cron / one-shot. If nobody runs it, the (small, private) variant objects accumulate.
- **The supabase `list_prefix` is unit-untested** (no Supabase in CI, like the other supabase
  methods + the Gupshup adapter) and **loads the full listing into memory** — bounded by
  school×media count at v1 scale; a paginated walk is the scale-up. The local_fs path + the fake
  are fully tested.
- **Age-based, not send-log-aware** — it reaps by object age, not by cross-referencing
  `whatsapp_send_log`. Simpler + safe (the 24h default is far past the 1h URL TTL); a send-log-tied
  rule is unnecessary precision.

## What's next (the rest of W3)

- **W3b — delivery receipts:** a public Gupshup webhook endpoint correlating by the
  `provider_message_id` W2 already stores → a per-send delivery status; medium-risk (the first
  unauthenticated route), useful once real messages flow.
- **W3c — send-to-all-in-an-event (the flagship):** a NEW backend worker + queue (the backend has
  none today) + per-`(media,student)` dedupe (so a whole-event re-run can't double-bill) + an
  event-level preview/confirm. Highest cost/risk; best done after the live Gupshup smoke confirms
  the per-student send works.
- Per-school sender numbers are already essentially shipped (W1/W2) — an operational runbook item,
  not a code slice.
