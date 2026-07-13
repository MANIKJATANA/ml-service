# 0041 — Product Build BP4: Distribution ("Photos are ready")

**Date:** 2026-07-14
**Status:** Accepted

## Context

The roadmap's flagship (`product/03`, after BP1–BP3) — the product's single biggest gap: delivery was **pull-only**
(nothing reached the student; they had to know to log in and hunt — fails lens **X1**, target **T1**). BP4 makes the
product *announce* new photos. **Backend + frontend; one migration (`0005`); no ML change, no new backend
worker/poller.** Two owner decisions this session: (1) build the in-app/service-level delivery now + a **multi-channel
notifier seam** (email/WhatsApp are future drop-ins that compose together or one at a time; ship a `log` channel now);
(2) trigger = **both** — auto-announce on completion (default) + a per-event staff override + manual notify. Design
validated by a Plan agent (its blocker on keying off `completed_at` is fixed below).

## Decisions

### 1. The student "new photos" signal is DERIVED (no worker, no ML change)
Rather than write per-student rows at completion (which would need a writer the backend doesn't have at that moment),
the signal is derived and composed **in-Python** in `NotificationService` (never a SQL join against the isolated
`matches` seam — protects the Phase-7 contract test), mirroring `GalleryService.student_events`:
- An event is **announced** when `notified_at IS NOT NULL` (staff manually notified) **OR** `(auto_notify AND
  completed_at IS NOT NULL)` (auto + has completed at least once).
- A student's **new photos** = their matched events (`list_student_appearances` grouped by event) ∩ the roster (drops
  since-deleted students) that are announced and **unseen** — unseen = *no read* **or** `seen_at < effective` where
  `effective = COALESCE(notified_at, completed_at)`, so a staff **re-notify** resurfaces it.

### 2. Migration `0005` + a set-forward `completed_at` (touches decisions/0027)
`events` gains `auto_notify BOOLEAN NOT NULL DEFAULT true` + `notified_at TIMESTAMPTZ`; new `notification_reads`
(per-`(student, event)` `seen_at`, `UNIQUE(student_id, event_id)` upsert key + student/event indexes, all FKs
CASCADE). **`EventRepository.set_processing(QUEUED)` no longer clears `completed_at`** — it's set-forward, so an
auto-announced event doesn't un-announce mid-redistribute (the Plan agent's blocker). The ML worker still overwrites
`completed_at` forward on each completion, so this is consistent end-to-end. `auto_notify` is a **live gate** (turning
it off un-announces an auto-only event) — simple + redistribute-robust; documented.

### 3. Multi-channel notifier seam (email/WhatsApp = future drop-ins)
A `NotificationChannel` port (`notify(event: NotificationEvent)`, best-effort) + a `CompositeNotifier` that fans out
to a **list** of channels resolved from `BE_NOTIFICATION_CHANNELS` (comma list, default `"log"`; empty → no-op) via a
new `NOTIFICATION_CHANNEL_REGISTRY` → memoized `container.notifier()`. A failing channel is logged and skipped (never
blocks the others nor fails the request). `log` channel now (structlog, **PII-free**: ids + count, never name/email).
`NotificationEvent` is immutable + carries the student contact so a future email adapter needs no service change.

### 4. Honest limitation — auto drives only the in-app signal
Manual "Notify students" stamps `notified_at` (committed) **then** fans out to the channels inline. **Auto has no
outbound push** — there's no backend process at completion, so auto only drives the derived in-app signal; sending
email/WhatsApp on auto needs a future notification worker (or an ML→backend completion signal). FE copy reflects this:
the toggle says "auto-announce **in-app**"; the button "Notify students" also sends via channels.

### 5. Routes, permissions, frontend
- Staff (new `Permission.NOTIFICATION_SEND`, admin+teacher) on `events.py`: `POST /v1/events/{id}/notify` (400 on
  archived/not-completed) + `GET /v1/events/{id}/notifications` (roster); the **auto toggle** rides `PATCH …/{id}`.
- Student on `me.py` (reuse `gallery:view_own`): `GET /v1/me/notifications` (unseen tally + announced events) +
  `POST /v1/me/notifications/{event_id}/seen`.
- FE: an authoritative student **nav badge** ("N new", accent) + a `/me/events` banner (marks events seen **on
  unmount** so the banner/badge persist the whole visit then clear cross-device — no flash); a staff **DistributionCard**
  (auto-announce toggle + "Notify students" + a "Notified · Seen" roster). **This supersedes BP3's client-side
  `useNewSince`** (localStorage), which is removed — the server signal is authoritative + cross-device.

## Verification

- BE gate green: ruff + mypy + layering + **275 passed, 19 skipped**. New: `test_notification_service.py` (derived
  announce/unseen, auto vs manual, re-notify resurface, archived-still-visible, zero-matched, roster, composite
  best-effort + empty no-op), `test_notification_routes.py` (RBAC + tenant + seen flow), and **gated real-Postgres**
  (`notification_reads` upsert + the `set_processing` set-forward). **Migration `0005` applied + reversed cleanly on
  real Postgres** (full `0001`→`0005` up + down).
- FE gate green: `eslint` + `tsc --noEmit` + `next build`.
- **2× review→fix loop:** R1 (correctness/SQL/tenant/hooks/migration) — no bugs (Core-insert `id` default, fan-out
  ordering, tz-safe compares, and the set-forward change all verified). R2 (edge/quality/a11y/PII) — fixed the accent
  nav-badge `aria-label` (was "N need attention"), a stale `set_processing` docstring, and added the three edge tests;
  PII + copy-honesty confirmed clean.

## Follow-ups

Deferred (documented): **real outbound channels** (email/WhatsApp adapters + `BE_SMTP_*`/provider config) and an
**auto-outbound worker**; the `announced_at`-stamp-on-read refinement for non-retroactive `auto_notify`. **Next: BP5 —
Trust & accuracy loop** (needs-review lane, confirm/reject, report-a-miss). Supersedes BP3's `useNewSince`
([decisions/0040](decisions/0040-product-build-BP3-student-receive-experience.md)).
