# 0091 — Per-student "Download all" on the event gallery's By-student tab

- **Date:** 2026-08-30
- **Status:** implemented (FE gate green; self-reviewed). **Committed + pushed.**
- **Scope:** the small BP26 follow-on flagged in [decisions/0081](0081-product-build-BP26-v1-staff-download.md) as
  "an easy follow-on — a per-student download on the gallery 'By student' tab". **FE-only — no backend change, no
  migration, no ML change, no new dependency, no new permission, no new env var.**

## Context

Owner request: on the event gallery's **By student** tab (the students filter), give a per-student **Download all** —
download the selected student's photos **from this event** as one zip. This is the event-scoped sibling of BP26 v1
(decisions/0081), which added a staff per-student "Download all" on the student *detail* page (that one spans **all**
of a student's events; this one is **just this event**).

## Decision

`EventStudentPhotos` (`frontend/app/(school)/events/[eventId]/gallery/page.tsx` — the component the By-student tab
renders below the `FilterChips` student filter) gains a **"Download all N"** button in a small header row above the
`PhotoGrid`:
- It zips the **same media the tab already shows** for the picked student — `useEventStudentMedia(eventId, studentId)`
  (the effective set, BP5 corrections applied) — via the streaming `useDownloadAll`, entries named
  `{event_date}-nnn`, zip `{Student-Name}-{Event-Name}-photos-{date}.zip`.
- `ByStudent` threads the active student's `name` down (from the already-fetched `useEventStudents` list);
  `EventStudentPhotos` reads the event name/date via `useEvent(eventId)` (SWR-deduped with the page's own call — no
  extra request).
- **Entitlement reused, not widened:** the per-photo mint is the same entitlement-gated `GET /media/{id}/download`
  staff already use to render every tile in this tab; both staff roles hold `gallery:view_all`. No new endpoint, no
  bypass.
- Honest download states mirror the sibling staff surfaces (student detail + the event-gallery bulk download):
  cancelled → silent, all-failed → error, capped → "the first N of M" (sticky), partial → "saved N of M" (sticky),
  full → success. A11y mirrors BP26 (button-label flip + an `sr-only` `aria-live` progress line).

## Correctness (self-reviewed)

- **Rules of Hooks:** every hook (`useEventStudentMedia`/`useEvent`/`useToast`/`useMemo`/`useState`/`useCallback`/
  `useDownloadAll`) runs before the component's early returns.
- **Per-student re-key:** switching the student chip re-fetches `useEventStudentMedia` → `mediaIds` recomputes →
  `useDownloadAll` re-keys; during the new student's load the tab shows the skeleton (the button isn't shown until the
  media is present).
- **Effective set:** the count/zip is the student's *effective* photos in this event (a rejected match excluded, an
  `added` one included) — consistent with what the tab renders.

## Files changed (1)
`frontend/app/(school)/events/[eventId]/gallery/page.tsx` (+ the imports `Download`, `useCallback`, `toISODate`,
`sanitizeFilename`).

## Verification

FE `npm run lint` + `npx tsc --noEmit` + `next build` clean; the gallery route stays dynamic (`ƒ`). No backend suite
delta (no backend change). No FE test harness (the repo norm) — verified by the gate + the manual-walk logic.

## Honest limits

- The non-streaming **500-cap** (BP9) applies on Firefox/Safari (surfaced by the capped toast); desktop Chrome/Edge
  streams the full set.
- "All" = the **effective** set for this event (BP5) — can differ from the raw ML `media_count` shown on the chip if a
  match was rejected/added.
- One `useEvent` read per By-student visit (SWR-deduped with the page — effectively free).
