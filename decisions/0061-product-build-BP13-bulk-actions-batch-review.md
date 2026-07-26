# 0061 — Product Build BP13: Bulk actions & batch review

**Date:** 2026-07-27
**Status:** Accepted

## Context

Round-2 roadmap ([`04`](../product/04-improvement-roadmap-round-2.md) §BP13, theme E / lenses P5, X2):
everything is one-at-a-time. When the ML flags an ambiguous match **needs_review** (BP5), staff must
open **each photo** to confirm/reject; at a real event that's 100+ decisions, so review gets skipped and
BP5's trust loop goes unused. Same for archiving a term's events and grabbing several photos. BP13 adds
the "…to many at once" verb across three surfaces, **reusing what BP5 and BP9 already built** — no
migration, no ML change.

Per the owner-approved plan (an HTML explainer + a decisions Q&A, 2026-07-27), three decisions: **scope =
all three** (batch review + bulk event archive + multi-select photo download); **no auto-confirm** (manual
multi-select only — the lane is still confidence-sorted); **a one-click "Reject all remaining"** guarded by
a confirm dialog (rejecting hides photos from students).

## Decision (BP13)

Two tiny endpoints + selection UI. **No migration** (reuses `match_corrections` + `events.status`), **no ML
change**, **no new permission** (reuses `match:review` / `event:manage`).

### Backend

- **Batch review** — `ReviewService.set_verdicts_batch(school_id, event_id, decisions, corrected_by)`:
  each decision is exactly the single BP5 `set_verdict` write to the `match_corrections` overlay (same
  hide-from-student gate on a reject, same undo, same `resolves_review`/dashboard-count semantics), applied
  to many pairs. **Tenant-safe by construction**: the event's ML appearances are fetched once
  (`list_event_appearances`, event+school scoped) into a `(media_id, student_id) → appearance` map; a
  decision whose pair isn't in that map is **silently skipped** — so a crafted `media_id` can never write a
  correction for another event or school, and there's no per-pair round-trip. `_require_event` runs first
  (foreign event → 404). Route `POST /v1/events/{id}/review/batch` (`match:review`); `BatchReviewRequest`
  caps the batch (2000) and the verdict is `confirmed`/`rejected` only (`added` → 422).
- **Bulk event status** — `EventRepository.set_status_bulk(school_id, event_ids, status)` is one
  tenant-scoped `UPDATE … WHERE school_id AND id IN (…)` (mirrors BP11a's `set_group_bulk`): a
  foreign/malformed id is silently skipped; returns the count updated. `EventService.set_status_bulk` +
  `POST /v1/events/bulk-status` (`event:manage`, registered **before** `/{event_id}` so the literal wins);
  `BulkEventStatusRequest` caps at 500 + a `status` enum.

### Frontend

- **Batch review lane** (`(school)/events/[eventId]/gallery` Needs-review tab): every ambiguous match is
  flattened to a per-(photo, candidate-student) pair, **sorted by confidence** (obvious ones on top), with
  a checkbox each + a "Select all". **Confirm selected** / **Reject selected** send the ticked pairs via
  `batchReview`; **Reject all remaining** (a `ConfirmDialog` — "hides those photos from the students")
  rejects *every* pending pair. Each action clears the selection, refetches the lane, and
  `globalMutate("dashboard")` so the "N to review" badge drops. A per-tile "Open photo →" still deep-links
  to the single-photo `AppearanceEditor` for nuanced cases.
- **Events multi-select** (`(school)/events` list): a checkbox column (select-all-on-page + per-row) + a
  bulk bar (**Archive** / **Restore** / **Clear**) calling `bulkEventStatus`. Selection is **derived**
  (`items.filter(e => selected.has(e.id))`) so a filter change that drops rows can never act on a hidden id
  (the BP11a "derived, not effect-reconciled" guard).
- **Multi-select download** (staff gallery All-photos tab): `PhotoGrid` gains a `selectionMode` (staff
  `grid` variant only — the student masonry surface is untouched); a tile click **toggles selection**
  instead of opening the lightbox (`aria-pressed` + a checkmark overlay). **Download N** reuses BP9's
  `useDownloadAll(selectedIds)` (streams to disk, bounded memory, each recorded in the BP8b audit); a
  cancelled save dialog (`n === 0`) stays in select mode (no false success toast).

## Why

- **Reuse, don't rebuild.** A batch confirm/reject is the single `set_verdict` in a loop; multi-select
  download is `useDownloadAll` over a subset; bulk archive is `events.status` set on a set. The only
  net-new is two thin endpoints + selection state — which is why BP13 needs no migration and no ML change.
- **Tenant safety without a new gate.** The batch validates pairs against the event's own appearances, so
  it inherits BP5's isolation + hide-from-student overlay exactly — no second security surface to get
  wrong.
- **No auto-confirm, guarded reject-all** (the owner's calls). Confirming only ever *shows* a student more
  photos (safe); rejecting *hides* them, so the one-click "reject all remaining" always asks first. The
  confidence sort keeps manual triage fast without a threshold heuristic.
- **Selection is derived, not effect-reconciled** — a stale selected id (after a filter change or a lane
  refetch) is filtered out before any request, so a bulk action can never touch a row the user can't see.

## Security

- **No cross-tenant / cross-event write** in the batch: the appearance map is event+school scoped and a
  pair outside it is skipped; `_require_event` 404s a foreign event first. The bulk-status `UPDATE` is
  `WHERE school_id AND id IN (…)`, so a foreign id is never touched.
- **A batch reject hides the photo from the student identically to the single reject** — it writes the same
  `match_corrections` row, so the BP5 effective-appearance download gate applies unchanged (no bypass).
- **Permissions unchanged**: batch review = `match:review`, bulk-status = `event:manage` (both admin +
  teacher); a student/unauthorized → 403, no token → 401. Caps → 422; a bad verdict value → 422.

## Alternatives considered

- **Auto-confirm ≥ a confidence threshold** (a one-click "confirm everything ≥ X%"). Declined by the owner
  for v1 — manual multi-select + a confidence sort is the chosen trade-off; the threshold heuristic is a
  documented future add.
- **A server-side "reject all remaining" endpoint.** Unneeded — the FE already has the full pending set
  (the lane) and sends it through the one batch endpoint; a dedicated endpoint would duplicate the logic.
- **A cross-event global review queue.** Deferred — batch review stays per-event (the existing lane); one
  "all pending reviews everywhere" queue is a future add.
- **A bulk download endpoint.** Unneeded — download + audit already exist per-photo; multi-select is pure
  FE over `useDownloadAll`.

## Consequences

- **No migration, no ML change, no new dependency, no new permission, no new env var.**
- **Honest limits (documented):** batch review is **per-event** (no global queue); **no auto-confirm** (the
  lane is confidence-sorted instead); the batch loops per-pair upserts (bounded by the cap — a set-based
  upsert is a future optimization); multi-select download is the staff `grid` variant only and inherits
  BP9's non-streaming-browser 500-photo cap; the events bulk bar acts on **loaded** rows (a "select every
  match across all pages" would need a server-side bulk-by-filter — out of scope).
- **Verification:** BE ruff + mypy + **543 passed / 36 skipped** + layering; `test_bp13_bulk.py` (batch
  applies-many / skips-a-non-event-pair / stamps `resolves_review` / foreign-event 404 / reject-hides-from-
  student / staff-only / 422s; bulk-status tenant-scoped / archive+restore / event:manage / 422) + a gated
  real-Postgres `set_status_bulk` tenant-scope round-trip on a **throwaway** DB (`bp13_migtest`, dropped;
  dev `app` untouched). FE tsc + lint + `next build` green. 2× review→fix loop, gate green after each. No
  commit / push without an explicit request.
