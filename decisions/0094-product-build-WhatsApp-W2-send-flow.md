# 0094 — WhatsApp W2: the send flow

- **Date:** 2026-08-31
- **Status:** implemented (BE + FE gates green; 2× review loop SHIP). **Not yet committed (awaiting owner review).**
- **Scope:** the third slice of the owner-locked **WhatsApp auto-send** track ([0092](0092-product-build-WhatsApp-Phase0-student-mobile-optin.md)
  Phase 0, [0093](0093-product-build-WhatsApp-W1-provider-foundation.md) W1). W2 is the **actual send** — staff send a
  student their photos inline on WhatsApp. **BE + FE; migration `0023`; no ML change, no new dependency.** The whole
  flow is built + tested against the **fake sender**; the real Gupshup delivery stays a deferred live smoke.

## Context

W1 built the provider seam but wired the sender into nothing. W2 wires it into a real send: a staff member opens a
student, confirms the cost, and the system sends each of that student's photos as an inline WhatsApp image. This is the
flagship — it spends real money and delivers real messages — so the owner confirmed the money/consent-touching
decisions before code.

## Owner + technical decisions

- **A · Send model = student-centric** (owner): staff send ONE student ALL or a SELECTED subset of that student's
  **effective** photos. One recipient per action → the confirm dialog states the exact cost, and a mis-click can't
  message a whole class. (Photo-fanout — select photos → each goes to everyone in it — was rejected as higher
  cost/consent risk; a documented future option.)
- **B · Endpoint = one backend endpoint that loops server-side** (the BP27 bulk pattern), best-effort per media, with
  ONE budget check — centralizes cost control (an in-browser pool would do N budget checks with N race windows).
- **C · Permission = a new `whatsapp:send`, granted to school_admin + teacher** (the `notification:send` precedent —
  teachers distribute too).
- **D · The ≤5 MB enforcement** (W1-deferred) lives in `make_whatsapp_variant`: resize to max_edge, then step quality
  down (to a floor) then edge down until the encoded bytes are ≤ `whatsapp_image_max_bytes` (4.8 MB, under WhatsApp's
  5 MB with headroom); an un-shrinkable image → `None` → the media is `failed`, never sent over-cap.
- **E · Budget cap = 12,000 sends per school per calendar month** (owner) — counted from `status='sent'` rows since
  the UTC month start; covers a full whole-school event without touching settings; configurable.

## Decision

`WhatsAppShareService.send_student_photos(*, school_id, student_id, media_ids, actor_user_id, actor_role)` — a pure
orchestration over ports with this **exact gate order** (fail fast, before any spend):
1. Tenant-scoped `student_repo.get(school_id, student_id)`; a foreign/missing student → `NotFoundError` (**404 before
   anything**).
2. `config.enabled` false → `ValidationError` (400) "not enabled".
3. Resolve `sender = config.sender_number or default_sender_number` (empty → 400) + `template` (None → 400).
4. **Consent gate**: `not whatsapp_opt_in` OR `mobile_number is None` → 400, **zero sends** (server-authoritative — the
   FE button-disable is not relied on).
5. **Effective media set** — `GalleryService.student_media` (the BP5 `effective_student_pairs` overlay, **REUSED, not
   re-derived**): a `rejected` appearance is dropped, an `added` one included. If the client passed `media_ids`, they
   are **intersected** with the effective set — any id the student does NOT effectively appear in is recorded
   `skipped "not entitled"`, so **a crafted/foreign/rejected `media_id` can never reach `send_image`** (R1 proved this
   unbypassable by construction).
6. Budget: `remaining = cap − count_sent_since(school_id, since=UTC month start)`.
7. Best-effort per-media loop (BP27 pattern): `remaining <= 0` → `skipped "budget"`; produce the ≤5 MB variant (None
   → `failed`); upload it to a deterministic per-media key `{prefix}/{school_id}/{media_id}.jpg` (overwritten on
   re-send) + mint a short-lived signed URL; `send_image(to, image_url, template, sender, caption)` → `sent`
   (records `provider_message_id`, `remaining -= 1`), on `UpstreamError`/`ValidationError` → `failed` with a static
   PII-free reason. One media's failure never aborts the batch.

Returns a `WhatsAppSendSummary {results:[{media_id,status,reason}], sent, failed, skipped}`.

- **Migration `0023`** (`whatsapp_send_log`, down_rev `0022`): append-only per-send audit + the budget counter —
  `id` PK, `school_id` (FK CASCADE), `student_id`/`media_id`/`actor_user_id` (FK **SET NULL** — the spend/audit row
  outlives an erased student/media/actor), denormalized `actor_role`, `sender_number` (the platform SENDER, **never
  the recipient**), `status` (sent/failed/skipped CHECK), `provider_message_id`/`error` (PII-free) nullable,
  `created_at`; indexes `(school_id, created_at)` (budget count) + `(school_id, student_id, created_at)`.
  `WhatsAppSendLogRepository` (postgres `record` + `count_sent_since` + a fake) + ORM mirror.
- **Route** `POST /v1/students/{student_id}/whatsapp-send` (`whatsapp:send`, tenant from token, `WhatsAppSendRequest
  {media_ids: list|null}` capped at 1000 → 422) → `WhatsAppSendResponse`. Container memoizes `whatsapp_share_service()`
  — the **first wiring of `whatsapp_sender()` into a service**.
- **PII**: the recipient number is never a column, never in an `error` string (static literals only), never in the API
  response, and is **redacted** in the Gupshup `UpstreamError` (`_redact` → last-4 only). `whatsapp_api_key` stays
  container-only.

### Frontend

`components/whatsapp/send-photos-button.tsx` — a **"Send N on WhatsApp"** button (disabled with a visible reason when
the student isn't opted-in / has no number) → a `ConfirmDialog` stating the true cost ("Send N photos to {student} —
uses N WhatsApp messages") → `use-whatsapp-send` (a thin action hook — the server loops, not the browser) → an honest
summary toast (sent=0 → error; partial → sticky info; full → success), with an **over-budget skip surfaced distinctly**
("N skipped (monthly WhatsApp limit reached)") from a plain skip, and an `aria-live` SR summary. Wired into the student
detail "Appears in" section (beside BP26 Download-all) and the event gallery By-student tab (reads the active student's
opt-in/number via `useStudent`).

## Verification

- **Backend gate:** ruff + mypy (194 files) + layering clean (`whatsapp_share_service`/`whatsapp_image` import only
  ports — no httpx/PIL/pydantic/fastapi); **pytest 802 passed / 51 skipped** (+ a gated real-Postgres send-log
  round-trip).
- **Migration `0023`** verified **up→down→up on a throwaway Postgres** (`wa_w2_migtest`, dropped; dev `app` untouched)
  — columns/nullability, the four FKs' `ON DELETE` (CASCADE + 3× SET NULL), both CHECKs, both indexes confirmed via
  `information_schema`.
- **Tests** (18 service + 12 route + image + permission/registry/container/gated): the gate truth table
  (disabled/not-opted-in/no-number/no-template/no-sender each **send nothing**); **rejected appearance requested by id
  → skipped, not sent** + `added` → sent; happy path (fake `.sent` = N with the resolved sender/template/signed URL,
  N `sent` log rows, `to` == mobile_number); partial-failure isolation; **budget cap stops sends** + zero-remaining;
  ≤5 MB un-shrinkable → failed; **PII-free** (no log row / error / response contains the number); **tenant 404 before
  any send**; permission matrix (**teacher allowed**, student/platform 403); over-cap 422.
- **Frontend gate:** lint + tsc + `next build` clean; `/settings/whatsapp` static, the two send surfaces dynamic.
- **2× review loop:** **R1 (correctness/tenant/consent/anti-rejected-photo/budget/PII/migration) — SHIP, 0 blockers**:
  the crafted-`media_id` path is provably unreachable, the consent gate is server-authoritative, the budget cap can't
  be exceeded within a request (only a bounded concurrent-request race, documented), the number is never
  logged/stored/returned, tenant isolation is double-enforced (ML seam + school-scoped media re-filter). **R2
  (cost-safety/edge/a11y/copy/lifecycle) — SHIP, 2 should-fix + 3 nits applied**: the distinct over-budget toast (the
  data was on the wire), the variant-object non-cleanup documented + "short-lived" wording corrected, the dead
  `loading` prop removed, the "Send 0" flash gated behind media-loaded, and the SR summary aligned on the all-failed
  path.

## Honest limits (documented)

- **The real Gupshup delivery is untested end-to-end** — needs the owner's live account + WhatsApp Business number +
  an approved Utility image-header template. W2 ships behind the `fake` default; flipping `BE_WHATSAPP_SENDER_IMPL=gupshup`
  + credentials + the template name enables it (the W2 smoke).
- **No server-side send dedupe (v1)** — the log records every attempt; a retry after a partial failure re-sends the
  already-sent photos (double cost). The FE button is disabled in-flight (no accidental double-fire).
- **Concurrent-request budget race** — two simultaneous requests can each pass the initial cap check (bounded
  overspend, not unbounded); a single request can never exceed the cap.
- **Variant objects are not reaped (v1)** — one small private JPEG per distinct media ever sent, at a deterministic
  key (overwritten on re-send); a cleanup job is a follow-up.
- **The confirm count is an honest upper bound** — the server may send fewer (de-dup/entitlement/budget), never more.

## What's next

- **The W2 live smoke** (owner setup): Gupshup account → WhatsApp Business number → one approved Utility image-header
  template → `BE_WHATSAPP_API_KEY` in `.env` + the template name in the settings screen → `BE_WHATSAPP_SENDER_IMPL=gupshup`
  → send to your own opted-in number and confirm delivery + a `provider_message_id`. Confirm the Gupshup adapter's
  `CONFIRM against Gupshup live docs` lines against the live API.
- **W3 (later):** send-to-all-in-an-event (a queue/worker), per-school numbers, delivery-status webhooks, a variant
  reaper.
