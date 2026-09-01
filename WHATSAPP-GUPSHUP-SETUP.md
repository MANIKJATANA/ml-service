# WhatsApp (Gupshup) — Setup & Go-Live Guide

This is the step-by-step to turn on **real** WhatsApp photo delivery. Everything in the app
already works against a built-in **fake** sender (nothing goes out); this guide flips it to the
**live Gupshup** provider.

- **You do:** create a Gupshup account, get a WhatsApp Business number, and get one message
  template approved (steps 1–3). ~30–60 min of clicking + waiting on Meta's template approval
  (minutes to a day).
- **The app already has:** the settings screen, the per-student "Send on WhatsApp" button, the
  ≤5 MB image handling, the 12,000/month budget cap, opt-in + audit logging.

> ### ✅ Adapter status (updated)
> The Gupshup adapter (`services/backend/src/backend/adapters/whatsapp/gupshup_sender.py`) has now
> been **confirmed against Gupshup's current public docs** — the endpoint, the `apikey` auth, the
> form fields, the template + image-header payload, and the success/response shape all match
> Gupshup's **self-serve** WhatsApp API. **The one thing you must get right:** the **Template ID**
> you paste in the settings screen must be the template's **UUID** from Gupshup (e.g.
> `c6aecef6-bcb0-4fb1-8100-28c094e3bc6b`), *not* its display name — see Steps 3 & 6. The only
> remaining unknown is **real delivery**, which can't be tested without a live account. So when
> you have the API key set + a template approved, **ping me and I'll walk the smoke test with
> you** and patch anything the live API surprises us with. A first-attempt `502` is still
> possible — that's just the signal to look at the exact response together.

---

## Prerequisites

- A **business** (Gupshup/Meta ask for a business name + basic details).
- A **phone number that is NOT currently on the WhatsApp or WhatsApp Business consumer app** — it
  becomes your sending number and must be free to register to a WhatsApp Business Account (WABA).
  A cheap dedicated SIM / virtual number works.
- Access to the backend's `.env` file (you edit it; never commit it — it's gitignored).

---

## Step 1 — Create a Gupshup account + a WhatsApp app

1. Sign up at **https://www.gupshup.io/** and log in to the dashboard.
2. Create a new **WhatsApp** app/channel (Gupshup's "WhatsApp API" product). Give it a name — this
   becomes your **app name** (the adapter sends it as the message source `src.name`).
3. Keep the dashboard open — you'll come back for the API key and the number.

> Tip: Gupshup offers a **sandbox** for quick testing to your own opted-in number before a real
> number/template is fully live. It's useful for a first smoke, but real business-initiated photo
> messages need an approved template + a registered number (steps 2–3).

## Step 2 — Get a WhatsApp Business number

1. In the Gupshup dashboard, start the **"go live" / onboard a number** flow. Gupshup walks you
   through creating/linking a **WhatsApp Business Account (WABA)** via Meta and registering your
   phone number to it.
2. Complete Meta **business verification** if prompted (raises your daily sending limits; a number
   can start at a lower tier without it).
3. Note the number in **E.164 digits only** (no `+`, spaces, or dashes), e.g. `919812345678` for
   India or `15551234567` for the US. This is your **sender number**.

## Step 3 — Create + submit ONE message template

Business-initiated messages (which is what "here are your photos" is) require a **pre-approved
template**. Create exactly one:

- **Category:** **Utility** (transactional). *Not* Marketing — Utility is cheaper and approves
  faster for "your photos are ready".
- **Header:** **Media → Image.** This is the part that carries each inline photo (the app fills in
  a fresh image link per photo at send time).
- **Body:** keep it minimal so it approves fast. Either fully static
  (e.g. `Here are your event photos.`) or one/two variables
  (e.g. `A photo from {{1}} — {{2}}`). Fewer variables = faster approval.
- **Buttons:** none needed.
- **Language:** your default (e.g. English).

Submit it. Meta review is usually minutes to a day. **Once approved, copy the template's ID — a
UUID** (e.g. `c6aecef6-bcb0-4fb1-8100-28c094e3bc6b`), shown next to the template in the Gupshup
template manager. You paste this **ID (not the display name)** into the app's settings screen —
Gupshup matches the send by template UUID, so the display name won't work.

> The app currently sends the template with **no body variables** (a minimal call). A fully-static
> body is the safest first template. If you want the event/school name in the message, that's a
> small enhancement we can wire when we confirm the adapter (it already accepts one caption param).

## Step 4 — Get your API key

In the Gupshup dashboard, find your **API key** (account-level or per-app, depending on Gupshup's
current UI). Treat it as a **secret** — it goes only in `.env`, never in code, chat, or a commit.

---

## Step 5 — Configure the backend (`.env`)

Edit the backend `.env` (the same file that holds `BE_DATABASE_URL` etc.). Add / set:

```bash
# Flip the provider from the built-in fake to real Gupshup:
BE_WHATSAPP_SENDER_IMPL=gupshup

# The ONE platform secret (from Step 4) — never commit this:
BE_WHATSAPP_API_KEY=<your-gupshup-api-key>

# Gupshup API base + your app name (from Step 1):
BE_WHATSAPP_BASE_URL=https://api.gupshup.io
BE_WHATSAPP_APP_NAME=<your-gupshup-app-name>

# The shared sender number (from Step 2), E.164 digits only. A school can override this in
# its settings screen; if a school leaves its sender blank, this is used.
BE_WHATSAPP_DEFAULT_SENDER_NUMBER=<your-number, e.g. 919812345678>

# (Optional — sane defaults already exist) cost + image knobs:
BE_WHATSAPP_MONTHLY_SEND_CAP=12000     # per school, per calendar month
BE_WHATSAPP_HTTP_TIMEOUT_S=30.0
BE_WHATSAPP_IMAGE_MAX_BYTES=4800000    # keep each photo under WhatsApp's 5 MB limit
BE_WHATSAPP_IMAGE_QUALITY_FLOOR=40
```

All of these are documented in `.env.example` (with placeholders). **Restart the backend** after
editing `.env` so it picks up the new values.

## Step 6 — Configure the school (in the app)

Sign in as a **school admin** → **WhatsApp** in the left nav (`/settings/whatsapp`):

1. **Enable WhatsApp for this school** — turn it on.
2. **Sender number** — leave blank to use the shared number from `.env`, or set this school's own
   number (must be a number you've registered in Gupshup).
3. **Template ID** — paste the **approved template's UUID** from Step 3 (e.g.
   `c6aecef6-bcb0-4fb1-8100-28c094e3bc6b`), **not** its display name.
4. **Business name** — optional display label.
5. Save.

## Step 7 — Prepare a test student (opt-in + number)

The app **only** sends to a student who is **opted in** *and* has a **mobile number**:

1. Open a student's detail page → the **WhatsApp** row → **Edit**.
2. Set the **mobile number** to **your own WhatsApp number** (E.164, e.g. `+91…`) for the test.
3. Check **"Opted in to WhatsApp messages"** → Save.

> WhatsApp policy: for the very first test, message your business number from your own phone first
> (or use Gupshup's sandbox opt-in) so your number is a known contact — this avoids delivery being
> blocked for lack of consent.

## Step 8 — The live smoke test

1. Make sure your test student **appears in at least one photo** (they're enrolled and an event
   with their photo has been processed) — the "Send on WhatsApp" button lives in their **"Appears
   in"** section (and on the event gallery **By student** tab).
2. Click **"Send N on WhatsApp"** → the confirm dialog shows the exact cost → **Send**.
3. **Expected success:**
   - The message(s) arrive on your WhatsApp — one image per photo.
   - The toast reads **"Sent N of N."**
   - A `whatsapp_send_log` row is written per photo with a `provider_message_id`.
4. **If it fails** (a `502` / "failed" toast): that's almost always the one-time adapter
   confirmation — **send me the error and I'll verify/patch the Gupshup endpoint, header, and
   template payload against the live docs.** (See the reality-check at the top.)

---

## Costs & limits (so there are no surprises)

- **1 photo = 1 WhatsApp message = 1 billed conversation** (inline images can't be batched into an
  album). A 30-student class of ~4 photos each ≈ 120 messages.
- **Budget cap:** 12,000 sends per school per calendar month by default (counts only successful
  sends). Over the cap, remaining photos are cleanly **skipped** and the toast says "monthly
  WhatsApp limit reached". Raise it via `BE_WHATSAPP_MONTHLY_SEND_CAP` when you consciously want a
  bigger send.
- **Billing is yours** (the platform's) — Gupshup bills the one platform account; schools don't pay
  per message. Utility-template pricing is the cheaper tier.
- The recipient's **phone number is never logged, stored in the audit row, or returned by the API**
  (it's redacted even in error messages).

## Known v1 limits (already documented in the code)

- **No automatic re-try dedupe:** re-sending after a partial failure re-sends the photos that
  already went (and re-bills them). The button is disabled while a send is in flight to prevent
  accidental double-clicks.
- **Send is per-student** (staff pick a student and send their photos). "Send to everyone in an
  event" is a future phase (W3).
- **Compressed image copies aren't auto-deleted** yet (one small private file per photo ever sent;
  a cleanup job is a future follow-up).

## What comes later (W3, optional)

- Send-to-all-in-an-event (needs a background queue so it survives large sends).
- Per-school sender numbers as a first-class flow.
- Delivery/read receipts (Gupshup webhooks) shown in the app.
- A cleanup job for the compressed image copies.

---

## Alternative: Meta WhatsApp Cloud API (instead of Gupshup)

You can send **directly through Meta's WhatsApp Cloud API** — your own WhatsApp Business account,
no BSP in the middle — by switching one env var. Everything else in the app (the settings screen,
the Send button, opt-in, budget cap) is identical; only the credentials + template field differ.

**Set up (once):**
1. Create a **Meta WhatsApp Business** account at [business.facebook.com](https://business.facebook.com)
   / add the WhatsApp product in [developers.facebook.com](https://developers.facebook.com).
2. Add/register a **phone number** → note its **Phone number ID** (this is your sender).
3. Generate a **permanent / system-user access token** (a short-lived dev token expires — don't use
   it for production).
4. Create + get approved a template with an **Image header** + a minimal body → note its **name**.

**Configure (`.env`):**
```bash
BE_WHATSAPP_SENDER_IMPL=meta
BE_WHATSAPP_META_ACCESS_TOKEN=<your-permanent-access-token>   # SECRET
BE_WHATSAPP_META_PHONE_NUMBER_ID=<your-phone-number-id>       # the sender
BE_WHATSAPP_META_API_VERSION=v21.0                            # keep current
BE_WHATSAPP_META_TEMPLATE_LANG=en_US                          # the template's language
```
Restart the backend, then in **`/settings/whatsapp`** the template field now reads **"Template
name"** (Meta matches by name, not a UUID) — paste the approved template's **name**. Enable it,
and send a test to your own opted-in number.

**Differences vs Gupshup:**
- Meta matches a template by its **name** (Gupshup uses the template UUID) — the settings field
  relabels automatically to "Template name" when Meta is active, and shows "Provider: Meta".
- For Meta the per-school **"Sender number" is ignored** — the sender is the `PHONE_NUMBER_ID`
  env var (per-school Meta numbers = multiple phone-number IDs = a future add).
- Keep `BE_WHATSAPP_META_API_VERSION` current — Meta deprecates old Graph API versions.

The same reality-check applies: the Meta adapter is written to Meta's Cloud API docs but the real
delivery is untested until your account is live — **ping me at go-live and I'll walk the smoke.**

---

### When you're ready

Get through the setup (account + number + an approved template), then ping me with your
**credentials set in `.env`** and the **template ID (Gupshup) or name (Meta)** — I'll **confirm the
adapter against the live API, patch it if needed, and walk the smoke test with you**. That's the
last mile to real delivery.
