# 0105 — WhatsApp send counts (per-photo + per-school, for costing)

**Date:** 2026-09-05
**Status:** Accepted

## Context

Every WhatsApp send already writes one immutable row to `whatsapp_send_log` (W2,
[0094](0094-product-build-WhatsApp-W2-send-flow.md)) — `school_id`, `media_id`, `student_id`,
`status` (`sent`/`failed`/`skipped`), `created_at`, PII-free (no recipient number). But that data
was only read for the monthly budget cap; nobody could see **how many WhatsApp images had actually
gone out**. The owner wants that visible for **costing** (each `sent` image = one WhatsApp message =
one cost unit): per **photo** (staff — "this photo was sent 4 times"; a photo sent to 2 students
counts 2) and per **school** for the platform owner ("how many images did this school send").

## Decision

Surface two **read-only counts** off the existing `whatsapp_send_log` (`status='sent'` rows). **No
migration, no ML change, no new dependency, no new permission** — the data is already saved.

### 1. Per-photo (staff)

- `WhatsAppSendLogRepository.count_sent_by_media(school_id, media_id) -> int` (tenant-scoped — a
  foreign media reads 0, never another school's rows) → `WhatsAppShareService.media_send_count`
  (a pure read; sends nothing) → **`GET /v1/media/{id}/whatsapp-log`** → `{sent_count}`, gated
  **`gallery:view_all`** (staff; reading a count needs no send permission), tenant from the token.
- FE: a small **`WhatsAppSendCount`** line ("Sent on WhatsApp N times" / "Not sent yet") on the
  **photo detail page** + the **staff lightbox** panel (gated on the same `showAppearances` staff
  flag as the download history; the student `/me` lightbox passes `enabled=false` so the
  `gallery:view_all` endpoint is never even called — defence in depth beside the server gate).

### 2. Per-school (platform owner, for costing)

- `WhatsAppSendLogRepository.sent_counts_by_school(since=None) -> dict[school_id, int]` — one
  cross-tenant grouped query (`since` filters to a boundary; used for the current UTC month).
- `AnalyticsService.estate_analytics()` (platform-only, `school:manage`) gains, per school,
  **`whatsapp_sent`** (all-time) + **`whatsapp_sent_month`** (this UTC month = the current bill),
  plus estate-wide **`whatsapp_sent_total`** / **`whatsapp_sent_month_total`**.
- FE: the **Estate health** page (`(platform)/estate`) gets a **"WhatsApp images sent"** headline
  card (This month + All time) and two sortable funnel columns (**WhatsApp (mo)** / **WhatsApp
  (all)**) so the owner can rank schools by cost.

## Alternatives considered / notes

- **A denormalized counter column on `media`** — rejected; the log is the source of truth and a
  `COUNT` is cheap at the bounded send volume (12k/school/month cap). No migration.
- **Per-tile badges on every gallery photo** — not done (clutter + N queries); the count lives on
  the per-photo inspection surfaces (detail + lightbox). A batched per-tile count is a future add.
- **This-month vs all-time** — the estate shows both (monthly maps to the WhatsApp bill; all-time is
  lifetime). `count_sent_by_media` (per-photo) is all-time.

## Honest limits

- The per-photo count has no `(school_id, media_id)` index (bounded volume → a school-scoped scan is
  fine); add one if send volume grows a lot.
- Counts are `status='sent'` only — a `failed`/`skipped` attempt costs nothing and is excluded.
- A row survives an erased media/student (FK SET NULL), so an all-time school total can include
  images whose media row is gone — correct for costing (the message was still sent + billed).

## Verification

- BE ruff + mypy clean (200 files); **859 passed / 51 skipped** (+ per-photo route/perms tests in
  `test_event_photo_fanout.py` and an estate all-time/this-month/`sent`-only/totals test in
  `test_bp14_analytics.py`); layering clean. FE lint + tsc + `next build` green.
- **2× review loop — both SHIP, 0 blockers / 0 should-fixes.**
  - **R1 (correctness / security / tenant):** verified the per-photo count can't leak cross-tenant
    (filters `school_id` from the token AND `media_id` → a foreign media reads 0, no existence
    oracle), the estate cross-tenant query is reachable ONLY via the `SCHOOL_MANAGE` platform route,
    the UTC month boundary matches the existing budget query, the fake matches the real adapter
    (`status='sent'`, `>=` since), the injected constructor arg order is right across the container +
    3 test sites, and the FE hook's `enabled` gate + the lightbox `showAppearances` wrapper keep a
    student token from ever calling the staff endpoint.
  - **R2 (edge / UX / a11y / copy):** confirmed the copy is honest against the backend (only `sent`
    counted; "sent to N students counts N"), the loading/error/empty states render cleanly (null, no
    flicker), a11y + contrast match the sibling `DownloadHistory`, and the estate columns/card are
    sortable + aria-correct + scroll cleanly. Applied its nits: moved the lightbox WhatsApp line
    **before** the download history (matching the photo-detail order) and dropped the redundant
    `enabled` prop (the `showAppearances` wrapper already gates the mount).
