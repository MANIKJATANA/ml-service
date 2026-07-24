# 0055 — Product Build BP9: Scale-ready lists & galleries

**Date:** 2026-07-25
**Status:** Accepted (implemented)

## Context

The Round-2 product review ([0054](0054-product-review-round-2-and-BP9-roadmap.md), theme D)
found the app's felt experience breaks at real-school scale (~800 students, ~120 events/yr, a
3rd-year student with ~900 photos). Only `GET /v1/audit/downloads` was paginated (BP8b); the other
list endpoints returned **unbounded** full sets, `GalleryService` **loaded the whole school
roster/event list into Python and filtered in-memory**, the FE did search/sort/filter **client-side
over already-fetched rows**, photo grids **mounted every tile**, and download-all **buffered every
blob** → OOM. BP9 is the owner-approved first Round-2 build — the low-risk substrate every later
phase's new views ride on.

**Owner decisions (this build):** **one phase** (not sliced 9a–9d — one decision doc, one gate, one
2× review loop; the breaking response-model change lands with the FE so there's no broken window);
**global count-sort** (sorting by count columns spans the whole list); **uniform infinite-scroll** on
every list + the galleries; **stream-to-disk** download-all.

## Decision

**Backend — server pagination on the 6 unbounded list endpoints** (students, events, staff, schools,
schools/{id}/admins, events/{id}/media), replicating the BP8b audit template:

- **Envelope + params.** One `{items,total,limit,offset}` `*PageResponse` (+ `from_page`) per
  endpoint over a generic service-side `Page[T]` (`services/pagination.py`). Offset/limit (not
  keyset — the lists need a live `total`, allow arbitrary-column sort, and scale is modest; the
  house `ORDER BY …, id` tiebreak already makes paging stable). Shared `api/pagination.py` Query
  params (`limit`/`offset`/`q`/`sort`/`dir` + a per-endpoint status filter); an out-of-range
  limit/offset or an unknown `sort`/`dir` → **422** for free (the `sort` param is typed as the
  endpoint's `*Sort` enum).
- **Two-path sort (the crux, §Why).** Row-native sorts (name/email/date) page directly in SQL
  (`list_page` + `count_page`). **Count-column** sorts (students by appearance/event count, events by
  media/matched/needs-review, schools by rollup counts) take a **whole-list id-scan**: fetch all
  matching ids (`list_ids`, id-only), sort them in-Python off a **school-wide** count dict (the same
  grouped query BP2 already runs), slice one page, hydrate it (`list_by_ids`) — so the isolated ML
  `matches` seam is **never** SQL-joined ([0028](0028-galleries-and-download.md)/BP4/BP5 invariant
  intact). New sort enums (`StudentSort`/`EventSort`/`UserSort`/`SchoolSort` + the `*_COUNT_SORTS`
  frozensets) are pure value types in `domain/models.py` (layering-safe); the two-path branch lives
  in `ListingService`.
- **De-rostering.** `GalleryService.event_students`/`student_events`/`media_appearances` now fetch
  **only the matched ids** via the new `StudentRepository`/`EventRepository.list_by_ids` (Media's
  already existed) instead of `list_by_school` + in-Python filter; `AuditService._compose` likewise
  fetches only the page's distinct event/student ids. The pure BP5 overlay helpers already give the
  exact id sets.
- **Migration `0011`** adds the composite indexes serving each default sort + name search
  (`(school_id, created_at, id)` / `(school_id, name, id)` on students/events, `(school_id, role,
  created_at, id)` on users, `(name, id)` on schools, `(school_id, event_id, created_at, id)` on
  media) — additive, reversible. New `BE_DEFAULT_PAGE_SIZE` (50) / `BE_MAX_PAGE_SIZE` (200) settings.

**Frontend — uniform infinite-scroll + windowed galleries + streaming download.** A generic
`useInfiniteList` (`useSWRInfinite`, `keepPreviousData`, resets to page 1 on any filter change) backs
every list hook; a shared `<LoadMore>` (IntersectionObserver sentinel + an always-rendered "Load
more" button [a11y / reduced-motion fallback] + a live "Showing N of M") drives loading. The five
list pages move `q`/`sort`/`dir`/`status` into state feeding the hook (search debounced 300 ms);
`SearchInput`/`SortableHead`/`FilterChips` are kept as the *controls* wired to server params (chip
counts sourced from the dashboard rollup, not in-memory rows — `FilterChips.count` is now optional).
`PhotoGrid` **windows** (mounts only the first N tiles, grows N via a sentinel; reset on a new
first-item via adjust-state-during-render) and, given `onLoadMore`/`hasMore`, fetches the next server
page at the end — so a 900-photo grid never mounts 900 tiles. `useDownloadAll` **streams** the
client-zip straight to disk via the File System Access API (`showSaveFilePicker` → `pipeTo`; bounded
memory, survives 900 photos), falling back to the buffered zip (capped at 500) where unsupported.

## Why

- **Global count-sort without breaking the seam.** The owner wanted "sort the whole list by
  most-photos." Those counts live in the ML-owned `matches` table, which the backend deliberately
  never SQL-joins. The **bounded id-scan** (id-only fetch + in-Python sort off the existing grouped
  aggregate + hydrate one page) delivers a true global sort while keeping that isolation — vs. the
  rejected alternative of relaxing the seam to `ORDER BY count`, an architectural reversal.
- **School-wide aggregate kept (not page-scoped).** The count dict is one grouped query bounded by
  matched entities — exactly what BP2 already ships. Scoping it to page ids was considered and
  dropped as needless surface; the win BP9 targets is the **full-row** loads (unbounded lists +
  gallery rosters), which are gone.
- **Uniform infinite-scroll** matches the app's existing `useInView` idiom and the owner's choice;
  the always-present "Load more" button keeps it keyboard- and reduced-motion-accessible.
- **Stream-to-disk** is native (no new dep, no CSP change vs. StreamSaver) and the only option that
  truly survives a 900-photo download; the capped buffered fallback covers Firefox/Safari.

## Alternatives considered

- **Keyset cursors.** Rejected — the lists need a live `total` (so a count is unavoidable anyway) and
  server-side arbitrary-column sort makes cursors awkward; offset over an indexed ≤800-row tenant
  slice is cheap at school scale.
- **Relax the `matches` seam for count-sort.** Rejected (see §Why) — the id-scan keeps the invariant.
- **StreamSaver.js / keep buffering.** Rejected as primary — a new dep + CSP cost, or an OOM on big
  sets; the FS Access API + capped fallback is cleaner.

## Consequences

- The 6 list endpoints now return `{items,total,limit,offset}` (a **breaking** response-model
  change) — intentional and shipped **with** the FE (one phase), so nothing is left broken.
- **Honest limits (documented):** offset paging can skip/dup a boundary row under a concurrent
  insert/delete (acceptable at this scale; keyset is the scale-up); a count-sort does one bounded
  id-only scan + one grouped aggregate (both bounded by the tenant slice, full rows only for the
  page); the **student `/me` gallery still fetches its media-id list whole** (bounded by the
  student's own matches, lightweight `{media_id,…}` rows) and relies on `PhotoGrid` windowing for the
  render cost — appearance/`/me` pagination is out of scope; the download-all fallback caps
  non-streaming browsers at 500 photos; the FE `MediaProcessingStatus` type stays `pending|completed`
  (the gallery media page has no status-filter UI). No ML change.
- **Verified.** Backend ruff + mypy + **403 unit** (+ the new BP9 pagination/de-rostering suite) +
  **22 gated real-Postgres** repo tests (incl. `ILIKE`-escaping + tenant scoping on a **throwaway**
  `bp9_migtest` DB, dropped; dev `app` DB untouched) + layering; migration `0011` verified
  up→down→up on that throwaway DB. Frontend `tsc` + `eslint` + `next build` green. New env vars in
  `.env.example`. 2× review loop.
