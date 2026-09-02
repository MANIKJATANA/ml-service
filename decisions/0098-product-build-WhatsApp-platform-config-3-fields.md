# 0098 — WhatsApp platform config: 3 DB-controlled fields (sender number, token, interim number)

- **Date:** 2026-09-03
- **Status:** implemented (BE + FE gates green; migration `0025` verified up→down→up on a throwaway
  Postgres; self-reviewed). **Not yet committed (pending the owner's go-ahead).**
- **Scope:** an owner-requested simplification of the [0097](0097-product-build-WhatsApp-live-test.md)
  platform WhatsApp screen so live-testing needs **no restarts and no `.env` edits**. Keep exactly
  **three fields**, all DB-controlled and showing their current value: **sender number**, **Meta
  access token**, **interim test number**. **BE + FE; migration `0025`; no ML change, no new
  dependency, no new permission** (reuses `SCHOOL_MANAGE`).

## Context

During the live smoke the owner hit two frictions on the 0097 screen: (1) the **Meta sender
phone-number ID** still lived only in `.env` (`BE_WHATSAPP_META_PHONE_NUMBER_ID`), so changing which
number sends meant a file edit + restart; and (2) the screen carried an **"Interim test mode"
toggle** separate from the interim number, which read as clutter ("the interim-number option isn't
there"). The ask: **"keep only 3 things — sender number, token, interim number — and control them
all from the DB (not `.env`) so I can change them directly without restarting."**

0097 already made the **token** DB-controlled (a per-send `token_provider`, DB-first with an env
fallback). This decision extends that pattern to the **sender phone-number ID** and drops the
separate interim toggle.

## Decision

- **New column `platform_config.sender_number`** (migration `0025`, down_rev `0024`; additive,
  nullable — existing rows adopt NULL → the container falls back to the env var). It holds the **Meta
  sender phone-number ID** (for the Meta provider this IS the phone-number ID in the send URL, not a
  `+country` number). Threaded through the ORM, the `PlatformConfig` domain VO, the repo port +
  postgres adapter + fake, the service, the API schemas, and the FE.
- **Sender ID resolved fresh per send:** the Meta sender now takes a `phone_number_id_provider`
  (async callable) instead of a static kwarg — mirroring 0097's token provider. The container wires
  `_meta_phone_number_id()` = `platform_config.sender_number`. So a sender-number edit in the UI
  takes effect on the **next send, no restart**. `_post` awaits both providers per call; the sender
  stays memoized.
- **DB-only, NO env fallback (owner follow-up).** The Meta **token** and **sender phone-number ID**
  are resolved from the DB ONLY — the env fallback was **removed** and the two settings fields
  (`whatsapp_meta_access_token`, `whatsapp_meta_phone_number_id`) + their `.env.example` entries
  (`BE_WHATSAPP_META_ACCESS_TOKEN`, `BE_WHATSAPP_META_PHONE_NUMBER_ID`) **deleted**, so a stale
  `.env` value can never be silently used. `_meta_token()` / `_meta_phone_number_id()` return `""`
  when the DB is unset (a send then fails clearly). Only the non-secret Graph API plumbing
  (`api_version` / `base_url` / `template_lang`) + the provider selector (`BE_WHATSAPP_SENDER_IMPL`)
  stay in env. Consequence: after deploy the token + sender MUST be set at **Platform → WhatsApp**
  before any send works. (`.env` itself is owner-edited — the code no longer reads those keys, and
  `Settings` uses `extra="ignore"` so a leftover line is harmless.)
- **The interim toggle is gone; the interim path is gated purely on the interim number's presence.**
  `WhatsAppShareService.send_student_photos` now branches on `if platform.interim_test_number:` (was
  `interim_mode AND interim_test_number`). **Set a number → all "Send on WhatsApp" divert to it;
  clear the field → normal delivery.** The `interim_mode` **column is kept but vestigial** (no
  destructive migration; the domain/repo/service still carry it, the API/UI dropped it).
- **Clearable fields (the key correctness point).** Because turning interim OFF now means CLEARING
  the number, the partial-update semantics were made explicit and uniform:
  - The service `_clean` no longer collapses `""` → `None`. Instead: **`None` = the field was
    omitted → leave unchanged; a provided string is trimmed and passed through (`""` = clear).**
  - The repo (`_merge_str`) + the fake merge uniformly: **`None` → keep current, `""` → clear to
    NULL, a value → set it.** So a caller distinguishes "unchanged" from "cleared".
  - The FE sends: the token as `trim() || null` (blank = keep — it's write-only and never shown),
    and the sender/interim as `trim()` (a visible field cleared to `""` clears server-side).
- **API surface (3 fields):** `UpdatePlatformConfigRequest` gains `sender_number`, drops
  `interim_mode`. `PlatformConfigResponse` gains `sender_number` (returned in full — it is NOT a
  secret, so the current value is visible), drops `interim_mode`. The Meta **token stays masked**
  (`token_set` + `token_last4` only) — never returned in full, never logged.
- **FE:** the `(platform)/whatsapp` page shows the three fields seeded from the current config
  (sender + interim visible, token write-only with a "set · ending 1234" hint), a **live warning
  banner while an interim number is set** ("every send goes to the test number, not students — clear
  it for normal delivery"), and an honest note that all three apply on the next send with no restart
  + the closed-24h-window caveat.
- **Guide** (`WHATSAPP-GUPSHUP-SETUP.md` / `.html`) updated: the "interim mode toggle" wording
  replaced with the three DB-controlled fields + "setting an interim number turns it ON (no toggle)".

## Verification

- **Backend gate:** ruff + mypy (133 files) + layering clean (domain/services import no IO lib);
  **pytest 853 passed / 52 skipped** (+3: a `sender_number` partial-update service test, a
  clear-interim-turns-off service test, a `_meta_phone_number_id` provider DB-vs-env test; the route
  put/get now covers `sender_number` and asserts `interim_mode` is gone; the gated postgres round-trip
  adds `sender_number` + an explicit `""`-clears-interim step).
- **Migration `0025`** verified up→down→up on a **throwaway** Postgres (`wa_sender_migtest`, dropped;
  dev `app` DB untouched — the column appears, drops, re-adds).
- **Frontend gate:** lint + tsc + `next build` clean; `/whatsapp` stays `○` static.
- The dev `app` DB is **not** touched by hand — the compose `backend-migrate` service applies `0025`
  on the next `docker compose up --build`.

## Honest limits (documented)

- The **interim toggle is replaced by number-presence** — leaving an interim number set diverts ALL
  "Send on WhatsApp" to it; the live warning banner + the "clear to resume normal delivery" copy
  guard against forgetting. `interim_mode` remains a vestigial column (not dropped, to avoid a
  destructive migration).
- "Sender number" is the **Meta phone-number ID** — for the Meta provider that is the sender; for a
  future Gupshup path the per-school `sender_number` is the relevant knob (this platform field maps
  to the Meta URL's `phone_number_id`).
- The Meta token stays **DB-stored + masked** (0097's owner-approved tradeoff); it is the one field
  never shown back in full.
- Everything is still gated on the owner's live Meta setup (a verified business + WhatsApp number +
  an approved image-header template + a non-expiring system-user token) for real, non-interim
  delivery — this decision only changes where the three values live and how they're edited.

## What's next

- The owner rebuilds the stack (`docker compose up --build` → `backend-migrate` applies `0025`,
  then the backend + frontend start with the new code), signs in as **platform admin → WhatsApp**,
  and sets the three fields. For the current interim smoke: paste a fresh token + set the interim
  number → "Send on WhatsApp" delivers the intro + real photos to that number (inside the 24h
  window). For production: clear the interim number and use the approved template path.
