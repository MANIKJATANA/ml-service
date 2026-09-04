# 0099 — WhatsApp is platform-only: remove the per-school config, move it to the platform config

- **Date:** 2026-09-04
- **Status:** implemented (BE ruff+mypy+pytest+layering green; migration `0026` verified up→down→up on a
  throwaway Postgres; FE lint+tsc+build green; 2× review loop). **Not yet committed (pending the
  owner's go-ahead).**
- **Scope:** the owner's request — *"remove the WhatsApp tab from the school; only the app (platform)
  admin sets WhatsApp and all."* This is **Phase 1** of a 3-phase plan
  (`student-photos-and-whatsapp-plan.html`, owner-approved); Phases 2–3 (the student "Appears in"
  event filter + the select-all/random send division) are pure-frontend follow-ups in later
  decisions. **BE + FE; migration `0026`; no ML change, no new dependency, no new permission.**

## Context

Through W1 ([0093](0093-product-build-WhatsApp-W1-provider-foundation.md)) WhatsApp was configured
**per school**: a `school_whatsapp_config` table + a school-admin `whatsapp:manage` permission + a
`(school)/settings/whatsapp` screen, holding `enabled` / `sender_number` / `template_name` /
`business_name`. The platform config ([0097](0097-product-build-WhatsApp-live-test.md)/
[0098](0098-product-build-WhatsApp-platform-config-3-fields.md)) held the **secret** side (Meta
token + sender phone-number ID + interim number).

The owner's v1 model is: **schools don't touch WhatsApp — the platform admin owns it all.** So the
per-school config is removed and its two send-relevant fields move to the platform config.

The one real catch (found in exploration): the W2 **send flow** read `enabled` + `template_name`
from the per-school config with **no platform fallback**, so simply hiding the school UI would strand
the production (template) path. The template therefore had to move to the platform config and the
send flow repointed there.

## Decision

- **Platform config gains `template_name`** (migration `0026`, down_rev `0025`; additive, nullable —
  existing rows adopt NULL → a send fails clearly, "set the approved template at Platform →
  WhatsApp", until one is set). Threaded through the ORM (`PlatformConfig`), the domain VO, the repo
  port + postgres adapter (`_merge_str`) + fake, the service (`_clean`), the API schemas
  (`UpdatePlatformConfigRequest`/`PlatformConfigResponse`, returned in full — not a secret), and the
  FE. The platform WhatsApp screen now has **four** fields: sender number · token · **template
  name** · interim number.
- **The send flow reads the platform config for sender + template** (`whatsapp_share_service.py`).
  The old gate — `if not config.enabled` (per-school) + `config.sender_number` + `config.template_name`
  — is replaced by reads off the `platform` config already fetched for the interim branch:
  - `sender = platform.sender_number or self._default_sender` → 400 "…set the sender number at
    Platform → WhatsApp" when absent.
  - `template = platform.template_name` → 400 "…set the approved template at Platform → WhatsApp"
    when absent.
  - **"Enabled" is implied by sender + template both being present** — there is no per-school enable
    flag any more (an explicit platform on/off toggle is a trivial future add). The **interim path
    is unchanged** (it still branches first on `platform.interim_test_number` and is unaffected).
  `WhatsAppShareService` drops its `WhatsAppConfigService` dependency (constructor + container
  wiring).
- **The per-school WhatsApp surface is removed** (not just UI-hidden):
  - **FE:** `(school)/settings/whatsapp/page.tsx` (+ the now-empty `settings/` dir),
    `lib/hooks/use-whatsapp-config.ts`, the school-admin nav entry, the `getWhatsAppConfig` /
    `updateWhatsAppConfig` endpoints, and the `WhatsAppConfigResponse` type.
  - **BE:** the router (`api/routers/whatsapp.py`) + its `main.py` registration, the service
    (`whatsapp_config_service.py`), the postgres adapter (`postgres_whatsapp_config.py`) + its
    registry entry (`WHATSAPP_CONFIG_REPO_REGISTRY`), the `WhatsAppConfigRepository` port, the
    `SchoolWhatsAppConfig` **domain** VO, the two config schemas (the send schemas stay in
    `api/schemas/whatsapp.py`), the `whatsapp:manage` **permission** (+ its `ROLE_PERMISSIONS`
    entry), the container methods, and the school-config tests. The `whatsapp:send` permission
    (school_admin + teacher) is untouched — only *configuration* moved to the platform.
- **The `school_whatsapp_config` table + its ORM model are left DORMANT** (no destructive migration):
  the ORM class stays in `db/models.py` (marked dormant) so the migration chain ↔ `Base.metadata`
  stay consistent; nothing reads or writes it. A future cleanup migration may drop the table.

## Verification

- **Backend gate:** ruff + mypy (283 files) + layering clean (domain/services import no IO lib);
  **pytest 836 passed / 51 skipped** (was 853/52 at 0098 — the delta is the removed school-config
  tests + a few added platform-config `template_name` tests). Coverage touched:
  `test_whatsapp_share_service.py` (the gate truth table now drives sender/template off the platform
  config; "unconfigured platform → 400" replaces "config disabled → 400"; interim tests use
  `_platform_config(interim_test_number=…)`), `test_whatsapp_send_routes.py` (platform-config seed;
  "unconfigured → 400"), `test_platform_config.py` (+ `template_name` service/route/round-trip
  asserts + a `test_set_template_name_and_partial_update`), `test_postgres_repos.py` (the gated
  platform-config round-trip threads `template_name`; the school-config round-trip removed),
  `test_container.py` / `test_registry.py` / `test_permissions.py` (school-config assertions removed).
- **Migration `0026`** verified up→down→up on a **throwaway** Postgres (`wa_0099_migtest`, dropped;
  dev `app` DB untouched — the `template_name` column appears, drops, re-adds).
- **Frontend gate:** lint + tsc + `next build` clean; `/whatsapp` stays `○` static.
- **No new env var** (`whatsapp_default_sender_number` stays — a last-resort Gupshup fallback used
  only if the platform sender is unset; Meta ignores it). No `.env` touched.

## Honest limits (documented)

- **No per-school WhatsApp any more** — there is no per-school enable flag or per-school sender; every
  school sends through the single platform sender/template. This is the owner's v1 intent; a
  per-school override (or an explicit platform on/off) is a future additive change.
- **"Enabled" is implied by sender + template being set.** An explicit global toggle would be a
  one-line add (a `platform_config.enabled` column + one gate) if the owner later wants a kill switch
  distinct from clearing the fields.
- The **dormant `school_whatsapp_config` table** is not dropped (avoids a destructive migration); it
  is orphaned code-side. A cleanup migration can drop it later.
- Real (non-interim) delivery still depends on the owner's live Meta setup (verified business +
  number + approved template + a non-expiring token) — this decision only changes **where** the
  sender/template live and **who** edits them.

## What's next

- **Phase 2** (FE-only): the student detail "Appears in" event filter — `All` + the latest few events
  as quick chips + a searchable "Filter events" picker for long histories.
- **Phase 3** (FE-only): divide the send/download — grid multi-select + "Select all (this view)" +
  "Select random N", acting on the selected `media_ids` (the send endpoint already accepts a subset).
- On deploy, the platform admin must set the **template name** at Platform → WhatsApp for real
  (non-interim) sends to work (the compose `backend-migrate` applies `0026`).
