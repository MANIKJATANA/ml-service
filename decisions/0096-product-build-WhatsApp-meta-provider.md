# 0096 — WhatsApp: a Meta Cloud API provider (env-configured, alongside Gupshup)

- **Date:** 2026-09-02
- **Status:** implemented (BE + FE gates green; 2× review loop SHIP). **Committed + pushed.**
- **Scope:** a second real WhatsApp provider — the **direct Meta WhatsApp Cloud API** — added
  **alongside** Gupshup, selectable by `BE_WHATSAPP_SENDER_IMPL`, with Meta's credentials as env
  vars. **BE + a small FE label change. No migration, no ML change, no new dependency, no new
  permission.** Owner ask: "isko env variable bnado and Meta API ka integration bhi krdo."

## Context

W1 ([0093](0093-product-build-WhatsApp-W1-provider-foundation.md)) deliberately made the WhatsApp
sender a pluggable seam — a `WhatsAppSender` port + a `WHATSAPP_SENDER_REGISTRY` name→class table +
a config-selected container branch — precisely so a second provider is a **new adapter + one
registry line + one container branch + its env credentials**, with no change to the W2 send flow,
the settings screen, or the DB. The owner wanted the option to send **directly through their own
Meta WhatsApp Business account** (the Graph API) instead of the Gupshup BSP. That's exactly the
seam's purpose; this decision cashes it in.

## Decision

A `meta` provider behind the existing seam. `fake` stays the default; `fake`/`gupshup` are
byte-for-byte unchanged (R1-verified).

- **`adapters/whatsapp/meta_sender.py` → `MetaWhatsAppSender`** — mirrors the Gupshup adapter
  (httpx, `raise_for_status()`, `httpx.HTTPError` → `UpstreamError`, `_redact(to)` on the
  recipient, the token NEVER logged). `POST {base_url}/{api_version}/{phone_number_id}/messages`
  with `Authorization: Bearer {token}`; a JSON template message with an **image-header component**
  (`{"type":"header","parameters":[{"type":"image","image":{"link": image_url}}]}`), a `body`
  component appended only when `caption is not None` (the share service passes `caption=None` →
  header-only). `_meta_to_receipt` parses `messages[0].id` (guarded against a non-dict/empty/
  no-`id`/non-dict-element body → `""`). A 2xx-with-`error`-body defensive check mirrors Gupshup.
  **Two Meta quirks (documented):** `sender_number` is **ignored** (the sender is the
  `phone_number_id` in the URL, not a body field — per-school Meta numbers = multiple phone-number
  IDs = a future add); Meta matches a template by its **NAME** (not a UUID). Version-sensitive
  lines flagged `CONFIRM against Meta Cloud API docs`.
- **Registry** (`wiring/registry.py`): `WHATSAPP_SENDER_REGISTRY` gains `"meta"`.
- **Container** (`wiring/container.py::whatsapp_sender()`): restructured into explicit `if fake /
  elif gupshup / elif meta / else raise ConfigurationError`; the meta branch reads
  `whatsapp_meta_access_token.get_secret_value()` (the secret read only here) + the other meta
  settings. `whatsapp_config_service()` now also passes `provider=self._s.whatsapp_sender_impl`.
- **Settings + `.env.example`:** a Meta block — `whatsapp_meta_access_token: SecretStr` (SECRET,
  placeholder-only), `whatsapp_meta_phone_number_id`, `whatsapp_meta_api_version` (`v21.0` — bump
  to current at go-live), `whatsapp_meta_base_url`, `whatsapp_meta_template_lang` (`en_US`). Reuses
  `whatsapp_http_timeout_s`. A note to use a **permanent/system-user** access token (a short-lived
  one expires).
- **Provider-aware settings screen:** `WhatsAppConfigResponse` gains `provider: str` (the active
  `whatsapp_sender_impl`, threaded via the config service's new `provider` property → both GET+PUT
  routes). The FE (`(school)/settings/whatsapp/page.tsx`) labels the **template field** by it
  (Gupshup → "Template ID"/UUID; Meta → "Template name") + shows a **"Provider:"** line, and — for
  Meta — the **"Sender number"** field's hint says it's **not used** (the sender is the env
  `phone_number_id`), so a Meta admin isn't misled into setting an ignored value.
- **Go-live guide** (`whatsapp-gupshup-setup.md` + `.html`): a "Using Meta WhatsApp Cloud API
  instead of Gupshup" appendix (Business account → phone-number ID → permanent token → approved
  image-header template → the env vars → paste the template **name**), and a provider-aware
  closing CTA.

## Verification

- **Backend gate:** ruff + mypy (199 files) + layering clean (`meta_sender.py` imports only httpx +
  domain; nothing leaks into domain/services); **pytest 828 passed / 51 skipped**.
- **Tests:** `_meta_to_receipt` parse (8 cases incl. non-dict/empty/no-`id`/non-dict-element →
  `""`); the container builds `meta` + memoizes + an unknown impl → `ConfigurationError`; the
  config-service `provider` passthrough; every `from_config`/`WhatsAppConfigService` caller updated
  for the new `provider` arg.
- **Frontend gate:** lint + tsc + `next build` clean; `/settings/whatsapp` stays `○` static.
- **Secret safety:** `whatsapp_meta_access_token` is `SecretStr`; `.get_secret_value()` is called
  ONLY in the container's meta branch; never in the adapter/logs/errors; `.env.example` is a
  placeholder.
- **2× review loop:** **R1 (correctness/secret/layering) — SHIP, 0 findings** (secret airtight,
  fake/gupshup byte-for-byte unchanged, `_meta_to_receipt` robust, provider passthrough complete,
  layering clean). **R2 (edge/config/docs) — SHIP, should-fix applied**: the Meta-aware
  sender-number hint (the main UX gap), the provider-aware `.md` CTA, sweeping the two stale
  two-provider comments (`adapters/whatsapp/__init__.py`, `settings.py`), and the non-dict-element
  parse test.

## Honest limits (documented)

- The **real Meta send is untested until a live account exists** (behind the `fake` default; a
  smoke is the owner's step — same posture as Gupshup).
- For Meta the per-school **sender_number is ignored** (the env `phone_number_id` is the sender;
  multi-number Meta is a future slice).
- The **Graph API version** must be kept current (`BE_WHATSAPP_META_API_VERSION`) — Meta deprecates
  old versions. Use a **permanent/system-user** access token.

## What's next

- **The live smoke** (owner, either provider): set `BE_WHATSAPP_SENDER_IMPL=gupshup|meta` + the
  creds + a template in settings, send to your own opted-in number, confirm delivery + a
  `provider_message_id` / `wamid…`.
- The paused W3 slices (W3b delivery receipts, W3c send-to-all) remain held until the live smoke.
