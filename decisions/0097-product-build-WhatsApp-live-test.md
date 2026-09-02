# 0097 — WhatsApp "live-test": UI-editable token + interim real-photo send

- **Date:** 2026-09-03
- **Status:** implemented (BE + FE gates green; 2× review loop SHIP after fixes). **Not yet
  committed (pending the owner's go-ahead — the plan approval authorized commit).**
- **Scope:** two owner-requested conveniences for **live-testing** WhatsApp: (1) a platform-admin,
  DB-stored, **UI-editable Meta access token** fetched fresh per send (the temp token expires
  ~daily); (2) an **interim free-form send** — from the existing "Send on WhatsApp" flow, a text
  intro + the N real Supabase photos to a **hardcoded test number** (config-gated). **BE + FE;
  migration `0024`; no ML change, no new dependency, no new permission** (reuses `SCHOOL_MANAGE`
  for the platform surface, `whatsapp:send` for the send).

## Context

Live-testing surfaced two frictions: Meta's **temporary token expires ~daily** and lived only in
`.env` (baked into the memoized sender at build → editing it meant a file change **+ restart**);
and there was no way to **see real photos arrive** before an approved image-header template exists.
The owner asked to paste a fresh token in the UI and to fire a real "text + N photos" send to a
test number for now (later the student's number).

**Security tradeoff (owner-approved, documented):** storing the Meta token in the DB reverses the
deliberate "no secret in the DB" design ([0093](0093-product-build-WhatsApp-W1-provider-foundation.md)/
[0094](0094-product-build-WhatsApp-W2-send-flow.md), env-only). It's implemented **platform-admin
only, never returned in full (only `token_set` + `token_last4`), never logged, with an env
fallback** — a deliberate convenience for the churning temp token.

## Decision

- **`platform_config` table** (migration `0024`, down_rev `0023`): a **1-row singleton** (PK `id` =
  `"platform"`) — `meta_access_token` (nullable, the secret), `interim_test_number` (nullable),
  `interim_mode` (bool default false), timestamps. ORM + domain VO `PlatformConfig`;
  `PlatformConfigRepository` (postgres **partial-update upsert** — set just the token, or just the
  number/mode — + a fake); a pure `PlatformConfigService`.
- **Routes** `GET`/`PUT /v1/platform/whatsapp-config` — **platform-admin only** (`SCHOOL_MANAGE`).
  `PlatformConfigResponse` exposes only `token_set` + `token_last4` (`token[-4:]` guarded) +
  `interim_test_number`/`interim_mode`/`updated_at` — **the full token is never in any
  response/schema/log**. PUT accepts an optional token (null = leave unchanged).
- **Fresh token per send (env fallback):** `MetaWhatsAppSender` now takes a `token_provider`
  (async callable) instead of a static token; each send `await`s it. The container wires
  `_meta_token()` = `platform_config.meta_access_token` (DB) **or** `settings.whatsapp_meta_access_token`
  (env) — DB-first, env-fallback. The sender stays memoized; only the token varies per call. So a
  token pasted in the UI takes effect on the **next send, no restart**.
- **Free-form send methods** on the `WhatsAppSender` port + all 3 adapters: `send_text` +
  `send_image_link` (Meta `type:text`/`type:image` with `link`+`caption`, no template — using the
  token_provider + `_redact` + the 2xx-error check; Gupshup via `/wa/api/v1/msg`; fake records).
- **Interim branch** in `WhatsAppShareService.send_student_photos`: runs **only** when
  `interim_mode` AND `interim_test_number` are set (read from the platform config); otherwise the
  existing **template path is byte-for-byte unchanged** (regression-tested). The interim path
  reuses the **effective media set** (`GalleryService.student_media`, BP5 overlay — a `rejected`
  photo is still excluded), the **budget cap**, and the **send-log**; it **skips the student
  opt-in/number consent gate** (the recipient is the test number, not the student). It sends a
  free-form text intro ("📸 Your school has shared N new photo(s) with you!") then each photo via
  `send_image_link` to the test number, best-effort. **The send-log `sender_number` records the
  platform sender / a `"interim"` marker — NEVER the recipient** (the "not-PII" invariant on that
  column; R1+R2 caught + closed a leak on this).
- **FE:** a platform-admin page (`(platform)/whatsapp`, gated by the group's `AuthGuard`) — a
  **write-only** Meta-token field (blank = keep the stored token; shows "set · ending 1234"), the
  interim test number, and an **interim-mode toggle** with a **warning banner shown while ON**
  ("every 'Send on WhatsApp' goes to the test number, not students — turn OFF for normal delivery")
  + an honest note that a closed 24h window means a send is accepted-but-not-delivered while the app
  still says "Sent". A nav entry + a `useWhatsAppPlatformConfig` hook + endpoints/types.
- The guide (`whatsapp-gupshup-setup.md`/`.html`) gained a "rotate the token in the UI (overrides
  `.env`, no restart) + interim test mode" note.

## Verification

- **Backend gate:** ruff + mypy (204 files) + layering clean (the token-provider is a plain callable
  wired by the container; `services/` import no IO lib); **pytest 850 passed / 52 skipped**.
- **Migration `0024`** verified up→down→up on a **throwaway** Postgres (dev `app` untouched) + a
  gated partial-update round-trip.
- **Tests:** platform config service (default/masking — `token_set`/`token_last4`, never the full
  token) + routes (platform-admin only → school-admin/teacher 403; partial update keeps the token);
  the token-provider (DB precedence + env fallback); the free-form adapters; the interim branch
  (text intro + N `send_image_link` to the **test number**, consent-gate skipped, budget respected,
  effective overlay reused so a rejected photo isn't sent, intro-failure doesn't abort);
  **interim-off = the template path unchanged** (regression); and the **PII invariant** — no
  recipient number in any log field incl. `sender_number` on **both** the failed AND the **sent**
  paths.
- **Frontend gate:** lint + tsc + `next build` clean; `/whatsapp` (platform) + `/settings/whatsapp`
  stay `○` static.
- **2× review loop:** **R1 (correctness/secret/tenant/migration) — SHIP**, one should-fix applied
  (the interim log's `sender_number` → the platform sender / `"interim"` marker, not the recipient).
  **R2 (edge/UX/copy/docs) — caught a BLOCKER**: the interim **sent** path still wrote the recipient
  into `sender_number` (the R1 fix missed the success path, and the PII test only exercised
  failures) → fixed on all four paths + a **sent-path** `sender_number` assertion added; plus S1 the
  interim-ON warning banner, S2 the closed-window "accepted but not delivered" copy, S3 the guide
  token/interim note.

## Honest limits (documented)

- **Interim free-form send only delivers inside the recipient's 24h window** (the test number must
  have messaged the business); a closed-window send is accepted but not delivered while the app says
  "Sent". Production (cold students) still needs an approved **image-header template** + a real
  number — this is an explicit interim/test mode.
- **Interim mode diverts ALL "Send on WhatsApp" sends to the test number while ON** — a testing
  toggle, off by default, with a live warning banner.
- **The Meta token is stored in the DB** (owner-approved) — platform-admin-only, never returned in
  full, env fallback retained. Not the hardened env-only posture.
- `_meta_token()` reads the DB once per send (one extra query; intentional — the token must be
  fresh; a short-TTL cache is a future refinement).

## What's next

- The **live smoke** stays the owner's step: paste a fresh token in **Platform → WhatsApp**, set the
  test number + turn interim mode ON, hit "Send on WhatsApp" for a student → the intro + real photos
  arrive on the test number (inside the 24h window). For production: verify the Meta business + add a
  real number + get an image-header template approved + a permanent token.
