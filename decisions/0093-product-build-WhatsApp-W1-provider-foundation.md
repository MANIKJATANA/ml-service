# 0093 — WhatsApp W1: provider foundation + per-school settings

- **Date:** 2026-08-30
- **Status:** implemented (BE + FE gates green; 2× review loop SHIP). **Not yet committed (awaiting owner review).**
- **Scope:** the second slice of the owner-locked **WhatsApp auto-send** track ([decisions/0092](0092-product-build-WhatsApp-Phase0-student-mobile-optin.md)
  shipped Phase 0). W1 lands the **provider-agnostic foundation** — a `WhatsAppSender` port + a fake + a Gupshup
  adapter (behind a config flag), one platform secret, a per-school `school_whatsapp_config` table + read/write path,
  a school-admin **WhatsApp settings** screen, and the ≤5 MB image-variant helper. **W1 sends NOTHING to students**
  (the send flow is W2). **BE + FE; migration `0022`; no ML change, no new dependency, no new env-var-secret in code.**

## Context

The owner's locked direction: staff select photos → the system **auto-sends each photo inline** to the student's
WhatsApp via a **platform-owned** provider account the platform pays for; the sender number is **configurable per
school**, defaulting to one shared app number. Before any sending exists, the app needs the provider seam + the
per-school config + the settings UI. That's W1 — a foundation that is fully gate-verified now, with the real provider
wiring behind a config flag (untestable end-to-end until an account/number/approved template exist).

## Decision

### Provider = Gupshup (over Wati) — a two-way door

Both wrap Meta Cloud API with media templates and fit "platform owns ONE account, ONE key". Gupshup wins for W1: its
**one-API-key + multiple-source-numbers + JSON send API** maps directly onto "one platform account, schools share a
number now / get their own in W3", whereas Wati is more per-tenant-instance/dashboard-centric. Because the provider
sits behind a **registry**, swapping to Wati later is a one-line change — nothing in the port or config is
Gupshup-specific. The real HTTP contract (endpoint / auth header / template payload / response id field) is
**provider-doc-dependent** and every such line in the adapter is flagged `CONFIRM against Gupshup live docs at
integration time`; the adapter ships behind the `fake`-default flag.

### The pieces

- **`WhatsAppSender` port** (`domain/ports.py`) + `WhatsAppReceipt` VO (`domain/models.py`) — deliberately DISTINCT
  from the BP4 `NotificationChannel` (that seam is PII-free/best-effort/fire-and-forget; this one carries the
  recipient number + image + approved template/sender and RETURNS a receipt or RAISES). One method:
  `send_image(*, to, image_url, template_name, sender_number, caption=None) -> WhatsAppReceipt`. `image_url` is a
  signed short-lived link WhatsApp fetches at send time (no bytes path). Errors reuse `UpstreamError` (→502) /
  `ValidationError` (→400) — no new error class.
- **Adapters** (`adapters/whatsapp/`): `FakeWhatsAppSender` (a REAL deterministic adapter — records calls, returns a
  `fake-<uuid>` receipt; the default) + `GupshupWhatsAppSender` (httpx, mirrors the ML-enroll client pattern; behind
  `BE_WHATSAPP_SENDER_IMPL=gupshup`). Registry `WHATSAPP_SENDER_REGISTRY` (fake|gupshup) + `WHATSAPP_CONFIG_REPO_REGISTRY`;
  container memoized `whatsapp_sender()`/`whatsapp_config_repo()`/`whatsapp_config_service()`. **The sender is wired
  into NO service and there is NO send endpoint** — W1 only proves the seam builds + resolves.
- **The ONE platform secret:** `whatsapp_api_key: SecretStr` in `settings.py` → `.env.example` **placeholder only**
  (never a real value; never read `.env`); `.get_secret_value()` is called ONLY in the container (wiring), never in
  an adapter/service/log/error. The per-school table holds **NO secret column**. Other settings: base URL, app name,
  HTTP timeout, default sender number, image max-edge/quality.
- **`school_whatsapp_config`** (migration `0022`, down_rev `0021`): `school_id` PK + FK→schools **ON DELETE CASCADE**,
  `enabled` (bool NOT NULL default false), `sender_number`/`template_name`/`business_name` (nullable), timestamps.
  One row per school, read by PK (tenant isolation inherent), no CHECK/index. `WhatsAppConfigRepository` port +
  `PostgresWhatsAppConfigRepository` (**upsert** via `on_conflict_do_update`, re-selects) + a fake. **Lazy, not
  seeded** — a missing row → the service synthesizes a `disabled` default (no `onboarding_service` change, no
  backfill).
- **`WhatsAppConfigService`:** `get_config` (row or a synthesized default), `set_config` (trim + blank→None each
  optional field; loose-validate `sender_number` via the Phase-0 `domain.phones.validate_mobile`; upsert). Tenant
  from the route (`tenant_of(actor)`), never a body field.
- **New permission `whatsapp:manage`** (school_admin ONLY — the `audit:view`/`class:manage` one-line-difference
  precedent). Routes `GET`/`PUT /v1/schools/whatsapp-config` (`api/routers/whatsapp.py`). **Registered BEFORE the
  `schools` router** in `main.py` so the literal `/whatsapp-config` isn't captured by `/v1/schools/{school_id}`
  (SCHOOL_MANAGE, platform-only) — verified by the route tests; no other `/v1/schools/...` literal collides.
- **The ≤5 MB image-variant helper** (built now, unused until W2): the `Thumbnailer` port gained optional per-call
  `max_edge`/`quality` overrides (default = instance config, so every BP17 caller is unchanged); `services/whatsapp_image.py::make_whatsapp_variant`
  reuses `ObjectStore.download_bytes` + the thumbnailer to re-encode a smaller variant. **NOT a hard byte cap** — it
  resizes/re-encodes only; the loop-down-quality-until-<5 MB enforcement is deferred to W2 (documented in the helper
  + port + `.env.example` so W2 doesn't assume a cap).

### Frontend

- A **WhatsApp** nav item (school_admin only) → `app/(school)/settings/whatsapp/page.tsx` (`RoleGate school_admin`):
  an Enable toggle + Sender number (with a hint that's truthful in all three states — shared-with-default,
  shared-without-a-configured-default, or the school's own number) + Template name (with provider-approval context)
  + Business name, and an honest note "**Saving configuration does not send anything yet — automated sending arrives
  next.**" `useWhatsAppConfig` SWR hook; `getWhatsAppConfig`/`updateWhatsAppConfig` endpoints;
  `WhatsAppConfigResponse` type (with `effective_sender_number`/`using_shared_number` computed server-side). The
  page stays statically prerenderable.

## Verification

- **Backend gate:** ruff + mypy (190 files) + layering clean (the two new services import only ports — no
  httpx/PIL/pydantic; httpx confined to the Gupshup adapter, PIL to the Pillow thumbnailer); **pytest 756 passed / 50
  skipped** at implementation (+ the R2 additions).
- **Migration `0022`** verified **up→down→up on a throwaway Postgres** (`wa_w1_migtest`, created via asyncpg, dropped;
  dev `app` DB untouched) — 7 columns / PK `school_id` / `enabled` NOT NULL / CASCADE FK confirmed via
  `information_schema`; a gated real-Postgres upsert round-trip (get None → upsert → get row → second upsert bumps
  `updated_at`).
- **Tests:** the fake sender (records + receipt); the Gupshup `_to_receipt` parser (5 cases —
  `messageId`/`message_id`/no-id-dict/non-dict/string → the one live-account-free Gupshup path); the config service
  (synthesized default, blank→None, `using_shared_number`/`effective_sender_number` incl. the empty-platform-default
  edge, malformed sender → 400); route round-trips (GET/PUT happy path, **teacher 403**, **platform-admin 403**,
  **two-tenant isolation**); the image helper (bytes for an image, None for a non-image/store outage); `test_registry`
  (both registries resolve — no typo), `test_container` (fake sender built + memoized), `test_permissions`
  (`whatsapp:manage` school-admin-only), `test_layering` green.
- **Frontend gate:** lint + tsc + `next build` clean; `/settings/whatsapp` is `○` static.
- **Secret safety confirmed:** `.get_secret_value()` only in the container; `adapters/whatsapp/` has zero log calls;
  the `UpstreamError` message carries only the recipient + error (no headers/key); `.env.example` is a placeholder;
  the table has no secret column.
- **2× review loop:** **R1 (correctness/tenant/secret/migration/layering) — SHIP, 0 findings** (secret handling and
  the router-ordering deviation both airtight and test-proven). **R2 (edge/config-defaults/a11y/copy/abstraction) —
  SHIP, 4 should-fix + 2 nits applied**: corrected the "≤5 MB cap" over-claim to "not a hard byte cap; enforced in
  W2" (helper docstring + port + `.env.example`); made the FE shared-number hint truthful when no platform default is
  configured; added provider-approval context to the template-name hint; added the `_to_receipt` unit test (the one
  real coverage gap); tightened the enable-toggle copy; noted the `updated_at` ORM/DDL `onupdate` divergence in the
  migration.

## Honest limits (documented)

- **The real Gupshup adapter is untested end-to-end** — it needs a live account + WhatsApp Business number + an
  approved media template, none of which exist yet. W1 ships it behind the `fake` default; the first W2 step is a
  live smoke once credentials exist.
- **The image helper is NOT a hard ≤5 MB cap** — W2 must enforce the byte ceiling before sending.
- **The `UpstreamError` (a future 502 at send time) surfaces the recipient number** — PII, not a secret; W2 should
  redact it when the send path goes live.
- **W1 sends nothing** — the sender builds + resolves but is wired into no service; there is no send endpoint.

## What's next (W2 — the send flow)

`POST /v1/students/{id}/whatsapp-send`, a `WhatsAppShareService` (gates on `whatsapp_opt_in` AND a non-null
`mobile_number`, mints a signed image URL, enforces the ≤5 MB variant, sends via the resolved sender), an FE **Send on
WhatsApp** button reusing the BP13/BP30 select-mode, a throttled pool, a `whatsapp_send_log`, and a per-school budget
cap. **Owner setup before the live smoke:** create a Gupshup account → a WhatsApp Business number → one approved
**Utility** media template (image header, minimal body) → put the API key in `.env` + the template name in the
settings screen.
