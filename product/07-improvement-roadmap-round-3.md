# 07 — Improvement Roadmap, Round 3 (BP18+)

> **This file = the proposed build order for Round 3's findings.** It sequences the fixes from
> [`06-product-review-round-3-ux.md`](06-product-review-round-3-ux.md) into approve-before-commit phases,
> exactly as `04` did for Round 2. **Nothing here is scheduled** — the build track is paused
> ([decisions/0063](../decisions/0063-park-remaining-backlog.md)); a phase starts only when the owner picks it
> and re-confirms scope. Each phase, when built, follows repo convention: its own `decisions/` record, docs
> first where warranted, the full gate, and the 2× review loop.
>
> **Parked items are not in this roadmap by construction** (owner decision, 2026-07-28): BP12 outbound
> email/share-links, BP15 accuracy-at-scale, BP16 lifecycle/retention, and the BP6 video timeline stay in
> `05-parked-backlog.md`, untouched. Every phase below is built from Round-3 findings only.
>
> _One phase per Round-3 theme (J–Q). Finding IDs (`R3-…`) reference `06`; every item traces to one._

---

## 1. The map — effort × impact

| Phase | Theme | Kills | Effort | Impact | Migration? | ML change? |
|---|---|---|---|---|---|---|
| **BP18** Account recovery & credential safety | J | **Critical #1** + 6 findings | **S–M** | ⛔→✅ a child can get back in without losing their photos | no | no |
| **BP19** Pipeline resilience & stall visibility | K | **Critical #2** + 5 findings | **M** | ⛔→✅ no event can strand invisibly; failures measurable | no | yes (worker/queue, no contract break) |
| **BP20** The arrival moment | L | 5 findings | **M** | the flagship student moment finally lands | no | no |
| **BP21** Say what it does | M | 9 findings | **S–M** | trust: every claim true, one vocabulary — strings + one slice of error plumbing | no | no |
| **BP22** Review loop, armed | N | 4 findings | **S–M** | review stops being guesswork; debt visible at the decision | no | no |
| **BP23** Run it on numbers | O | 9 findings | **M** | rates become levers; attribution window closed before it shuts | **yes** (1 col) | no |
| **BP24** Two-way doors | P | 5 findings | **M** | mistakes become recoverable; batch work survives errors | no | no |
| **BP25** Floor sweep | Q | ~12 items | **S–M** | AA restored, mobile calendar usable, state survives navigation | no | no |

**Recommended order:** **BP18 → BP19 → BP21 → BP20 → BP22 → BP25 → BP23 → BP24.**
Rationale: the two Criticals first (BP18 is small and defuses the worst failure mode in the product; BP19 is
the other no-workaround path); then BP21 because it is the cheapest High in the review (strings) and halves the
trust exposure; then the student moment (BP20) and the teacher loop (BP22); the floor sweep (BP25) slots
anywhere and could piggyback on any adjacent phase; BP23/BP24 close the tail. BP21 has zero dependencies and
can be pulled forward or merged into any phase's copy work.

---

## 2. The phases

### BP18 — Account recovery & credential safety *(Theme J — kills Critical #1)*

The product must be able to give someone back in without destroying why they came.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-A2-01/A4-01 | **`POST /v1/students/{id}/resend-invite`** — mirror BP7c's machinery exactly (`generate_temp_password` + `must_change_password` + shown-once `ProvisionedStudentResponse`); FE row action on the student detail + list via the existing `InviteResultDialog`. *This single slice retires the Critical.* |
| 2 | R3-A4-01 | Login-page help line: "Forgot your password? Ask your school to send you a new one." (+ the `?reason=expired` "you were signed out" line, R3-A4-08). |
| 3 | R3-A2-02/S3-02 | **Close-guards on shown-once credentials**: the bulk-import results dialog and `InviteResultDialog` confirm on dismiss when the credential wasn't downloaded/copied (track the click; optionally auto-download when `created > 0`). |
| 4 | R3-A1-02/S3-03/S5-05 | **Resend-invite honesty**: ConfirmDialog when the target is Active ("This replaces their current password"), staff + platform surfaces; relabel toward "Reset & resend invite". |
| 5 | R3-A4-08/S5-07 | "Change password" link in the `UserFooter` (the page exists; nothing links it) + the student's **name** in the shell. |
| 6 | R3-S5-08 | Last-admin guard: confirm + a "this is the school's only administrator" warning on Disable (the rollup already knows the count). |
| 7 | R3-A1-01 | **`PATCH /v1/schools/{id}`** (name, `max_teachers`, status) + Edit-school dialog and suspend/reactivate on the platform detail — the write-once school record. |

**Gap-type mix:** capability (slices 1, 7) + display/guards (rest). **Effort S–M** (slice 1 is S — proven
machinery; slice 7 is the M). **Not included:** session revocation on password change + "sign out everywhere"
(R3-S5-06 — needs a token-version column, i.e. a migration; propose as **BP18b** if the owner wants it) and a
student **disable** route (same slice family; fold into BP18b). No migration in BP18 proper.

### BP19 — Pipeline resilience & stall visibility *(Theme K — kills Critical #2)*

Every in-flight state gets an owner, an age, and an exit.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-S1-01 | **Unstick**: allow Process when the event has been in-flight past a threshold (`enqueued_at` age), or an explicit admin "reset processing" action — widen `event_service.py`'s guard the way BP8a widened it for `failed`. |
| 2 | R3-S1-01 | **A DLQ consumer** (ML-side worker or startup sweep) that flips the event's backend status to a visible failed state instead of letting DLQ'd jobs vanish acked. |
| 3 | R3-S1-02 | **Failure metrics**: `jobs_failed_total{reason}`, DLQ-depth gauge, in-flight-age gauge, `photos_failed_total` — the counters the "ALERT" log line has nothing to fire. |
| 4 | R3-S1-03 | Surface `enqueued_at` ("processing since …") + escalation copy past a threshold ("taking longer than usual"), replacing the eternal "updates automatically". |
| 5 | R3-S1-04 | The **second batch**: derive the events-list pill from counts (the detail page already does) and widen the dashboard alert predicate to "events with unprocessed photos". |
| 6 | R3-S1-10 | `failed` in the dashboard media summary + a "N photos failed processing" alert — no more "All processed" over failures. |
| 7 | R3-A2-09/A3-06/S3-05 | **Upload survival**: keep failed `File` handles + "Retry failed (N)" on the event uploader; a `beforeunload` guard on every long-op (`isUploading || busy`); nav-confirm on the upload page. |

**Gap-type mix:** capability (1–3, 7) + display (4–6). **Effort M.** Cross-service (BE + ML worker + FE), no
ML-contract break (mirrors BP8a's shape). **Not included:** orphaned-object reaping for event media (not a
numbered finding — note it in the phase decision as a known small leak), resumable/folder upload (R2 §3.3③'s
larger ask — still deferred).

### BP20 — The arrival moment *(Theme L)*

The student's "new photos" moment should open on the new photos, name them, and stay fresh.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-A4-02 | **Newest-first** default ordering for the student stream + event chips (FE reverse of the asc payload, or `desc` in the two reads). |
| 2 | R3-A4-02 | An **actionable banner**: render the unseen events (name + count — already in the fetched `notifications.events`) as links that set the filter; mark-seen **on view** (filter selected / tiles rendered), not on mount. |
| 3 | R3-S3-11 | **Un-freeze the signals**: `revalidateOnFocus` / a modest `refreshInterval` for the two badge keys + `dashboard` (scoped SWR config, not global). |
| 4 | R3-A4-03 | **The 60-chip wall**: chips for ≤ ~8 events; beyond that group by year/term from `event_date` (already served) with "Earlier" collapsed, or a searchable select — newest first. |
| 5 | R3-A4-05 | **Photos get their story**: event name + date in the lightbox panel (and into `alt`); optional tile scrim caption in the All view. |
| 6 | R3-A4-07 | **The save keeps the story**: zip entries `{event}/{date}-{nnn}.jpg`, zip named `my-photos-{date}.zip`, single saves `{event}-{nnn}`; honest capped-fallback copy; sticky partial toasts. |

**Gap-type:** display throughout (the backend already serves everything needed). **Effort M.**
**Not included:** the student-chrome pass (R3-S2-05 — the warm layout variant + `display-xl` hero); it's the
natural companion but a design-led slice — propose as **BP20b** so the owner can take the moment-fix without
the reskin, or both.

### BP21 — Say what it does *(Theme M — the strings phase)*

Every claim true, one vocabulary. Almost entirely copy; zero migrations; can merge into any phase.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-S2-01 | **One pipeline grammar** — pick the verb pair (proposal: **Match** / **Announce**) and sweep: buttons, toasts ("Matching started."), pills, checklist ("Announce to students"), dashboard alerts, analytics ("Announce rate" until BP23 makes it a real reach rate), estate column. |
| 2 | R3-A3-07 | **"Notified N" honesty**: "Announced to N students — they'll see it in My Photos"; surface the configured channels in the DistributionCard ("In-app only" today). |
| 3 | R3-S5-02 | **True scope claim**: "Private to you and your school's staff — other students only ever see photos they're in too." (both the hero and the empty state). |
| 4 | R3-S5-03 | **"How photo matching works"** — one static page linked from the student empty state + the review lane; a one-line confidence legend where percentages render. |
| 5 | R3-S5-04 | **The erasure dialog tells both sides**: destroys the match history (unrecoverable), keeps the event photos + anonymized download records. |
| 6 | R3-S5-11 | **Audit honesty, both directions**: the log's caption ("records saves made in the app — not views"); one line telling teachers downloads are recorded and admin-visible. |
| 7 | R3-A2-07 | "Pending" → **"No photo yet"** sub-label on photoless rows (lead L8). |
| 8 | R3-S3-08/09/10 | **Error truthfulness**: a shared 401 interceptor (mutate `auth/me` → the existing redirect); parse FastAPI 422 arrays into field messages; forward `Retry-After` through the BFF + humanize 429; stop toasting raw `str(exc)` on 500s. |
| 9 | R3-S2-09 + S5-09 + A2-12 + S2-*Lows* | The naming sweep: one brand string; "My photos" nav=h1; "photos" as the umbrella noun; the 30 MB hint on the event uploader ("Photos and videos up to 30 MB each"); "Downloaded as" → "Student (self-download)"; the stale "(soon) delegate"; the raw school-status enum; why-you're-changing-your-password framing. |

**Gap-type:** display (strings) except slice 8 (small plumbing). **Effort S–M** (slice 8 is the M). **Not
included:** any outbound channel (parked BP12) — slice 2 documents the in-app truth, nothing more.

### BP22 — Review loop, armed *(Theme N)*

Put the evidence where the decision is.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-A3-02 | **The reference face in the review tile** + `AppearanceRow` — `useStudentReferencePhoto` + `StudentAvatar` already exist and the endpoint is teacher-permitted. The single highest-leverage accuracy fix. |
| 2 | R3-A3-08 | **Review debt at the announce moment**: "N matches to review" in the DistributionCard + an announce-time confirm when debt > 0 (no hard block — the owner's no-auto-confirm stance stands). |
| 3 | R3-S2-02/A3-09 | **Reachability**: URL-addressable gallery tab (`?tab=review`); deep-link the dashboard alert and the list pill straight to it; "Open photo →" returns to the review tab (or opens the Lightbox, which already hosts the editor). |
| 4 | R3-A4-04/S3-04 | **"This isn't me" made safe**: ConfirmDialog with consequence copy + an undo window (student-scoped un-reject mirroring `not-me`'s membership check); surface student rejections in the staff review lane so disputes are seen. |

**Gap-type:** display (1–3) + a small capability (4's un-reject route). **Effort S–M.**
**Not included:** the face-box overlay (bbox exists ML-side with no API — M–L, note only); accuracy *metrics*
(→ BP23); threshold tuning (unchanged v1 stance).

### BP23 — Run it on numbers *(Theme O)*

Turn the rates the owner already has into levers — and close the attribution window before it shuts.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-S6-04/A1-04 | **Attribution**: `last_login_at` onto `UserResponse` → staff-list "Last sign-in" column + platform roster; surface `events.created_by`; **migration: `media.uploaded_by`** (nullable, SET NULL) recorded at register — every day without it loses history. |
| 2 | R3-S6-03 | **Reach, honestly**: aggregate per-event opens (`seen ÷ rostered` across announced events) into the analytics read; exclude archived from the delivery denominator (or the BP21 rename stands). |
| 3 | R3-S6-02/07 | **Saved + trend**: `count_distinct_subject_students` → a "Saved a photo" RateCard; `monthly_first_open_counts` (mirror of `monthly_upload_counts`) → the engagement trend that *can* decline. |
| 4 | R3-S6-09 | **Lists behind the rates**: a "never signed in" / "never opened" students filter the rate cards + alerts deep-link; an `undistributed` events filter for the dashboard alert (with R3-A3-01's list pill). |
| 5 | R3-S6-08/S5-10/A2-03/S1-08 | **The per-child + per-event answer**: an Engagement card on the student detail (events appeared/opened/last-opened/downloads — two existing reads); wire the Access log's already-plumbed event/student filters; a "Downloaded" count on the notify roster (S1-08 — every save already carries its `event_id`). |
| 6 | R3-S6-01/10 + A1-03/05 | **Estate with an age axis**: `created_at` / first-distributed / `stalled_since` dates on `SchoolFunnel` + a `not_started` flag + client-side column sort (lead L12); "days to first delivery" replacing one vanity total. |
| 7 | R3-S6-06 | **Accuracy visible**: query-only verdict-rate aggregates over `match_corrections` (confirms/rejects/"not me" by month; `needs_review ÷ matches` per event) → a Quality section in Program analytics. *(The model work stays parked BP15 — this is the metric only.)* |
| 8 | R3-S6-11 | Roster "ever opened" (first-seen) beside the reset-on-reannounce `seen`. |

**Gap-type:** display except the one column (slice 1). **Effort M.** **Migration: 1** (`media.uploaded_by`).
**Not included:** storage-bytes tracking (R3-S6-05's tail — needs upload-path changes; note as a future slice),
snapshot-table history lines (parked §C).

### BP24 — Two-way doors *(Theme P)*

Mistakes become recoverable; batch work survives errors.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-A2-05 | **Clearable tags**: explicit-null semantics on the event PATCH (per-field sentinel, revising the 0027 convention with owner sign-off) + restore "No category"/"School-wide"/empty-term options in the edit dialog; stop silently preselecting "Other" on create (lead L18). |
| 2 | R3-A2-11 | **The CSV error loop**: pre-flag in-file duplicate/invalid rows in the preview; "Download skipped rows" CSV on results — fix-and-reimport without transcription (lead L15). |
| 3 | R3-A2-06 | **Classes at CSV scale**: an optional `class` column on the student import (auto-create/assign) or a paste-emails bulk-assign box on the class detail. |
| 4 | R3-S3-06 | **Honest partial downloads**: unify the staff gallery on the student page's partial-toast; distinguish user-cancel from zero-saved; name entries (shared with BP20 slice 6). |
| 5 | R3-S3-01 + A2-10/A3-10 | The residue: create-teacher refreshes its roster; the notify roster collapses behind its summary with a Not-opened filter + pagination. |

**Gap-type:** mixed (slice 1 is the one backend-semantics change). **Effort M.** **Not included:** undo-toasts
for student/class/category delete (confirm-only stands — BP18's recovery work removes the worst consequence;
revisit only if misclicks show up in practice).

### BP25 — Floor sweep *(Theme Q)*

One pass restoring the D8 floor and the navigation fabric.

| Slice | Finding | What |
|---|---|---|
| 1 | R3-S4-01 | **The token swap**: data-bearing `text-ink-muted` → `text-ink-secondary` (table headers, StatCard labels, LoadMore, hints, trend labels) — the app-wide AA fix. |
| 2 | R3-S4-02 | **Calendar minimum**: `overflow-x-auto` + `min-w` (scroll, don't crush), the darker today-badge, drop-or-honor `role="grid"` (lead L5). |
| 3 | R3-S4-03/04/06 | Focus rings on the three naked links; ≥24px effective targets on the events checkboxes + toast dismiss; the input-border darkening (or `bg-surface` fill). |
| 4 | R3-S4-05 | Lightbox: a visible "← → · Esc" hint; suppress the window arrow handler while the video is focused (leads L10 + the 0043 conflict — revising a 0043-documented tradeoff, owner sign-off). |
| 5 | R3-A2-08/L7 | **URL state**: q/sort/dir/status/tab into the URL on the list pages + gallery (also unlocks BP22 slice 3 — build together). |
| 6 | R3-S2-08 | Per-page `<title>`s (route-segment metadata or a small document-title hook). |
| 7 | R3-S2-03/06/07 + S2-04 | The design residue: a brand moment on auth; a non-semantic category palette; `animate-spin` on the "distributing now" icon; spend or delete the dead `display-xl`/mono tokens (the temp-password dialog is the mono moment). |
| 8 | Lows | The bundled Lows worth batching: search-match highlighting (L19), students bulk-select parity (L14), scroll/window restore on back-nav (L17), an offline hint (L16), "Download all" repeated at the grid foot, skip-link + auth `<main>`. |

**Gap-type:** display. **Effort S–M** (each slice is small; the phase is the batch).
**Not included:** dark mode, per-page `aria-busy`, nonce CSP (parked §C refinements).

---

## 3. What this roadmap deliberately leaves alone

- **Below the line — Mediums consciously unscheduled** (real findings, no phase home; batch onto an adjacent
  phase if the owner wants them): **R3-A2-04** teacher-cap visibility on the school side (pairs naturally with
  BP18 slice 7's school PATCH or BP23's caps work) · **R3-A3-03** school-wide chip counts over class-scoped
  lists · **R3-A3-04** delegation invisible to its beneficiary (both fit a small BP25 add-on) · **R3-A3-05**
  the create→upload→process navigation tax (a BP22-adjacent speed slice).
- **The parked set** — BP12 (outbound reach — still the biggest known gap, still parked on effort/infra),
  BP15, BP16, BP6-timeline: excluded by owner decision; `05` remains their single record.
- **Documented honest limits** that resurfaced and were *not* re-opened: offset paging (keyset is the
  scale-up), the `/me/media` whole-list fetch + LIMIT-less ML-seam reads (0055), sync thumbnails (0056),
  fire-and-forget audit recording (0050), fixed-window rate limiting (0051).
- **Session revocation + student disable** (BP18b) and the **student chrome pass** (BP20b) — named as optional
  companions so their parent phases stay small.

## 4. How to use this file

Pick a phase → re-confirm scope (the phase table + its findings in `06` hold the context) → docs-first if the
phase warrants it → build behind the usual gate + 2× review loop → its own `decisions/` entry → update this
file (tick the phase) and `05` if anything new gets deferred. The recommended order is §1's; the owner may
reorder freely — only BP18/BP19 carry a "these are the Criticals" weighting.
