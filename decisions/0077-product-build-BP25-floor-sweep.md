# 0077 — Product Build BP25: Floor sweep (all four groups)

- **Date:** 2026-08-16
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** **BP25 (Floor sweep)** — Round-3 review theme **Q**
  ([0064](0064-product-review-round-3-ux.md), [`product/06`](../product/06-product-review-round-3-ux.md)),
  redeeming R3-S4-01..06 + R3-S2-03/04/06/07/08 + R3-A2-08 + the bundled Lows. **One phase, all four owner-chosen
  groups. FE-only — no backend/ML change, no migration, no new permission, no new dependency.**

## Context

Theme Q — "the floor's thin patches": a batch of small display/a11y/navigation gaps had accumulated across the app.
The one **High**: sub-AA data text everywhere (`--color-ink-muted #8890a0` ≈ 3.2:1 styled table headers, `<dt>`
labels, counts, hints, trend labels at 12px). Plus an unresponsive month calendar, sub-24px tap targets, three
naked links, an sr-only-only lightbox hint (+ the BP6/0043 arrows-both-seek-and-navigate conflict on a focused
video), **no URL state** on the lists (a filtered list wasn't shareable + didn't survive Back), **no per-page
titles** (every tab read "Photos"), a brand-less auth screen, a frozen "matching now" spinner, and category colors
that reused the exact status tones. Two Explore passes inventoried every surface. Owner: **all four groups, one
phase** (a large but mostly low-risk diff; the 2× review is the safety net).

## Decision

All FE-only (~41 files touched + 4 new: `use-document-title.ts`, `use-online-status.ts`, `use-url-state.ts`,
`highlight.tsx`).

### A. AA + a11y floor
- **Token swap (the High):** a filtered script swapped **data-bearing** `text-ink-muted` → `text-ink-secondary`
  (5.9:1) — 69 spots across 29 files — on lines WITHOUT `size-`/`placeholder:`/`aria-hidden`/`hover:text-`, so icons,
  placeholders, and hover-buttons correctly stay muted.
- **Calendar:** `overflow-x-auto` + `min-w-[600px]` (scroll, don't crush at 375px); today badge `bg-accent` →
  **`bg-accent-hover`** (6.29:1, was 4.47).
- **Focus rings** on the 3 naked links (audit + 2 estate); **≥24px tap targets** — the events bulk checkboxes +
  the toast dismiss wrapped/padded.
- **Lightbox:** a visible "← → · Esc" hint; **suppress the window arrow-nav when a `<video>` is focused**
  (`document.activeElement?.tagName === "VIDEO"`) — revises the 0043 tradeoff (owner sign-off via this group).
- **Per-page titles:** a `useDocumentTitle` hook wired centrally into `PageHeader` (covers most pages) + 4 direct
  callers (login / change-password / photo detail / My Photos).

### B. Design residue
- **Auth brand:** the "Photos" wordmark + an `Images` icon above the sign-in card + a `<main>` landmark.
- **Category palette:** new **non-semantic** `--color-cat-{1..6}-{soft,ink}` tokens (violet/teal/fuchsia/cyan/
  indigo/slate, all AA 6.4:1+) replace the status-tone reuse in `categories.ts` — a category can never read as a
  status.
- **Frozen spinner:** `animate-spin` on the dashboard "matching now" `Loader2` (respects the reduced-motion guard).
- **Mono credential:** `font-mono` on the shown-once temp password.

### C. URL state on the lists (R3-A2-08)
A shared **`useUrlParams`** (`use-url-state.ts` — get/set over `useSearchParams` + `router.replace(scroll:false)`,
atomic multi-param `set`) + **`useUrlListSort`** (`use-sort.ts`) put **q / sort / dir / status / category / term /
class / mine / tab** into the URL on the **students / events / staff / schools** lists — shareable + Back-safe,
mirroring BP22's gallery `?tab=`. Each page splits into a `*Content` inner (uses `useSearchParams`) wrapped in
`<Suspense>` by the default export (so the pages stay statically prerenderable). The debounced search reads the URL
for the FETCH, keeps a local input with an **adjust-during-render** Back-sync, and writes only once the debounce has
**settled to the current input** (so Back never re-adds a just-dropped `q`).

### D. Bundled Lows
- **Skip-link** (sr-only-until-focus → `#main-content` on `<main tabIndex={-1}>`, both shell branches) + the auth
  `<main>`.
- **Students bulk-select parity:** a checkbox column + a bulk **"Assign to class"** bar (reuses the BP11a
  `assignStudentsToClass` endpoint), selection derived stale-safe (BP13); the column is gated on the school having
  classes (else it'd be a dead action).
- **Offline hint:** `useOnlineStatus` (`useSyncExternalStore`) → an offline bar in the shell.
- **Search-match highlighting:** a `<Highlight>` (`<mark>`, regex-escaped) on the list name/email cells, fed the
  applied query.
- **"Download all" at the gallery foot** on the student surface.
- **Scroll restore:** the App Router restores scroll natively — no config change (see honest limits).

## Consequences / honest limits (documented)

- **FE-only; no backend/ML/migration/permission/dependency change.** `git status` shows only `frontend/`.
- **Scroll restore is App-Router-native** and does **not** survive the infinite-list reset-to-page-1 on filter
  change (a Back into a deep-scrolled list re-fetches page 1) — not a config knob; keyset restoration is a scale-up.
- **URL-state search settles via a 300ms debounce**, so the shareable URL lags the input by one debounce window.
- **Two custom categories can still hash-collide** to one hue (`hash(id) % 6`) — a visual aid, not identity
  (unchanged from BP11b).
- **Search highlight is name/email-cell only** — a student row matched on *email* (searched server-side) won't
  visibly highlight (only the name cell is wrapped).
- **Students bulk-select is class-assign only**, acts on the **loaded page** (BP13 stale-safe), and the column only
  appears when the school has ≥1 class.
- **The input resting border** (`hairline-strong`) is left as-is — a documented "quiet input" tradeoff (labels + a
  strong focus ring carry it).
- **Per-page titles are client-side** (`useDocumentTitle` in Client Components) — no server `metadata`/SEO, fine for
  an authed internal app; the first paint briefly shows the root title before the hook runs.
- Verified: FE **lint + tsc + `next build` green** (the list pages stay `○` static — the Suspense boundary preserves
  it); no BE/ML suite delta. **2× review loop — no blockers.** **R1** (correctness/races) traced the URL-state
  loop-safety on all 4 pages, the bulk-select stale-safe selection, the token-swap correctness (no wrongly-swapped
  icon), the Suspense boundaries, and the smaller pieces → **1 should-fix**: the debounced-search-vs-URL **Back
  bounce** (the lagging debounce re-added a just-cleared `q` for ~300ms) → fixed by writing only once the debounce
  settles to the current input. **R2** (a11y/AA/consistency/edges) — **no blockers**, all AA math verified (the 6
  category pairs, the today badge, the mark highlight, the offline bar) → **3 should-fix** applied: gated the
  students checkbox column on the school having classes (was dead UI otherwise), pointed the search highlight at the
  applied query (not the leading input), and lifted the skip-link above the offline bar — plus the honest-limits
  list above.
- **Next:** the owner picks the next Round-3 phase — the recommended tail is **BP23** (instrumentation) → **BP24**
  ([`product/07`](../product/07-improvement-roadmap-round-3.md)), plus the earlier **blocked** BP22 slice 4 (student
  "This isn't me" safety) whenever re-opened; a phase starts only on owner pick + scope re-confirm.
