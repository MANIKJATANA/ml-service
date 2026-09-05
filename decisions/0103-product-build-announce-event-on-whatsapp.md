# 0103 — "Announce on WhatsApp": whole-event fan-out from the event's Announce card

**Date:** 2026-09-05
**Status:** Accepted

## Context

After matching finishes, the event detail page's **Announce** card (`DistributionCard`) offered
only the in-app **"Announce to students"** (the BP4 "My Photos" signal). But in v1 there is **no
student login** — the in-app signal is dormant/unused — and the **real** distribution channel is
**WhatsApp** (staff send students their photos). Yet WhatsApp sending only existed as (a) a
per-student send on the student detail / By-student surfaces and (b) a per-selected-photos fan-out
on the event gallery "All photos" tab ([0102](0102-product-build-event-photo-fanout.md)). There was
**no one-click "announce this whole event to everyone in it, on WhatsApp"** at the announce moment.

The owner asked: **don't make it automatic** (after matching), but **at the announce spot, add an
"Announce on WhatsApp" action**.

## Decision

Add an **"Announce on WhatsApp"** button to the event's Announce card that sends **every appearing
student ALL the (effective) photos they appear in** for that event, over WhatsApp — reusing the
existing [0102](0102-product-build-event-photo-fanout.md) fan-out (preview → confirm → per-student
send). It is **manual** (never fires on completion); it is gated on the event being finished +
active (`canNotify`), exactly like the in-app announce.

**BE + FE — no migration, no ML change, no new dependency, no new permission** (reuses
`whatsapp:send`), no new env var.

### The mechanism: `media_ids = None` → the whole event

The fan-out's `media_ids` becomes tri-state, mirroring the existing student-centric send
(`WhatsAppSendRequest.media_ids=None → all of a student's photos`):

- **omitted / `null`** → the **WHOLE event** (every matched photo — "Announce on WhatsApp"),
- a **non-empty list** → only those **SELECTED** photos (the [0102](0102-product-build-event-photo-fanout.md)
  "All photos" tab behavior, unchanged),
- an **explicit `[]`** → **422** (`min_length=1` kept — a fan-out with no photos is a bug, not "all").

`GalleryService.event_photo_recipients(media_ids: list[str] | None)` — when `None`, includes **all**
effective pairs (no intersection); otherwise intersects with `set(media_ids)`. The **safety spine is
unchanged**: the `None` path still ranges **only** over THIS event's own effective pairs
(`list_event_appearances(school_id, event_id)` after `_require_event(school_id, event_id)`), so a
rejected pair is still excluded and it can never leak a foreign/other-tenant/other-event student or
fan a send outside the event. `WhatsAppShareService.send_event_photos(media_ids: list[str] | None)`
just passes it through — so **consent-skip, the sequential budget cap, best-effort per-student error
handling, interim divert, and PII-free logging are all inherited unchanged** (no new code path).

### Frontend

- `eventPhotoRecipients` / `sendEventPhotos` accept `string[] | null` (`null` → whole event).
- `SendToAppearingDialog` gains a **whole-event mode**: omit `mediaIds` → the SWR preview key is
  `"ALL"`, the title reads **"Announce all photos on WhatsApp?"**, the empty state reads "No students
  appear in this event's photos.", and the send passes `null`. Passing a `mediaIds` array keeps the
  [0102](0102-product-build-event-photo-fanout.md) selected-photos behavior byte-for-byte.
- `DistributionCard` gets **"Announce on WhatsApp"** (primary) beside the kept in-app announce
  (relabeled **"Announce in-app"/"Re-announce in-app"**, demoted to secondary — WhatsApp is the real
  v1 channel so it leads). Both gated on `canNotify`; the preview dialog shows **"N students · X
  messages"** so the cost is visible before confirming, and the budget cap protects.

## Alternatives rejected

- **Automatic send on matching completion** — the owner explicitly does not want it (a background
  outbound worker remains parked, per [0041](0041-product-build-BP4-distribution.md)'s honest limit).
- **Fetch all the event's media ids on the FE and pass them** — heavy/paginated (up to ~900); the
  `None`-means-whole-event server semantics is cleaner and reuses the existing precedent.
- **Overloading an explicit empty list as "all"** — kept `[]` → 422 (a genuinely empty selection is
  a bug); only omitted/`null` means the whole event.

## Verification

- BE ruff + mypy clean (200 files); **856 passed / 51 skipped** (+6 whole-event tests in
  `test_event_photo_fanout.py`: recipients-None-is-all, None-still-excludes-rejected, fan-out-None-
  sends-all, both routes accept omitted `media_ids`); layering clean.
- FE lint + tsc + `next build` green.
- **2× review loop** —
  - **R1 (correctness / security / async) — SHIP, 0 blockers / 0 should-fix / 0 bugs.** Verified the
    `None`-means-all path still ranges **only** over the event's own effective pairs
    (`list_event_appearances(school_id, event_id)` after `_require_event`), the rejected-pair
    exclusion survives, and there's **no** way a client widens entitlement via `None`; the fan-out's
    per-student `_resolve_targets` re-intersects (double intersection, defense-in-depth); the
    `Field(default=None, min_length=1)` guard was checked against the installed Pydantic 2.13.4
    (omitted/`null`→None, `[]`→422, over-cap→422); budget/PII/consent inherited unchanged; mypy
    clean. One nit applied: the two `events.py` route docstrings still said "SELECTED" (now note the
    whole-event case).
  - **R2 (edge / UX / a11y / copy) — SHIP, 0 blockers.** Confirmed the existing "All photos"
    selection caller is unaffected, the two-button hierarchy/a11y is sound, and no `onSent`/mutate is
    needed (a WhatsApp send changes nothing in the in-app roster). Applied its **should-fix** — the
    whole-event toast could be a **reasonless sticky** toast when the monthly budget clipped photos
    but no whole student was skipped; the tail now always carries a reason (students-skipped /
    failed / "N photos not sent — the monthly WhatsApp limit may be reached"). Applied its 2 nits —
    a scale-cue description in whole-event mode ("…this can be many WhatsApp messages.") and an
    explicit-`null` wire-format route test.

## Honest limits / notes

- Whole-event announce can be **many** WhatsApp messages (every appearing student × their photos) —
  the preview shows the total and the monthly budget caps it; still, it is a bigger action than a
  single-student send.
- The in-app "Announce in-app" button stays (dormant in v1) — WhatsApp is primary.
- Everything else inherits [0102](0102-product-build-event-photo-fanout.md)'s limits (consent-gated,
  no send dedupe, interim test-mode divert).
