# 0037 — Frontend polish + hardening (Phase F7)

**Date:** 2026-07-13
**Status:** Accepted

## Context

F1–F6 built the feature surface. **F7 is the final pass** — the cross-cutting polish/hardening the
earlier phases deferred: graceful error/404 pages, a mobile nav, an a11y sweep, consistent error UX,
dead-code removal, and a README. **No backend change.** This completes the frontend build-out (F0–F7).

## Decisions

### 1. Error boundaries + 404 (`app/{error,not-found,global-error}.tsx`)

There were none — an unhandled render error or a bad URL hit Next's defaults. Added:
- **`error.tsx`** — the segment error boundary (client, `{ error, reset }`). It deliberately uses
  **`reset`** (re-render), not 16.2's newer `unstable_retry` (re-fetch): this app's data errors are
  handled in-component via SWR + Retry, so a boundary hit is a *render* fault where a plain re-render
  is the right recovery — and we avoid depending on an `unstable_`-prefixed API.
- **`not-found.tsx`** — the router 404 (server component) for unmatched routes + `notFound()`.
- **`global-error.tsx`** — the root-layout fallback; it renders above the root layout so it can't use
  Tailwind/providers — kept minimal with inline styles whose hex values mirror the `@theme` tokens.
- The three full-page surfaces (`FullPageError`, `error`, `not-found`) were **unified into one
  `FullPageMessage`** (a real `<h1>` + description + action), killing a type-scale drift and giving
  heading navigation an anchor in one place. `global-error` stays separate (it can't use the tree).

### 2. Mobile nav drawer (`app-shell.tsx`)

The sidebar was `sm:flex` (desktop only) — mobile had no navigation. Extracted **`NavList`** +
**`UserFooter`** (shared by the sidebar and the drawer), and added a hamburger in the mobile header
opening a **Radix Dialog left-drawer** (focus-trap / Esc / scrim / focus-return) that closes on
nav-click (`onNavigate`) and on a `matchMedia` resize past `sm` (else Radix leaves the body
scroll-locked + focus trapped on a now-hidden panel). Removed the mobile header's **redundant** logout
icon — Sign out lives in the drawer's `UserFooter` (with the email/role context), consistent with
the desktop sidebar.

### 3. a11y sweep

- **`FilterChips` → a proper radiogroup**: roving tabindex (the checked chip is the single tab stop)
  + arrow-key nav (←/→/↑/↓ move + select), per WAI-ARIA — was a bag of Tab-through buttons.
- **Error announcement**: `EmptyState` gained an optional `role` prop; the **13 error states** set
  `role="alert"` so a screen reader announces the failure on mount (an assertive live region is
  announced on insertion). `GridSkeleton` got `role="status"` for gallery loads. This redeems the
  systemic gap deferred from F6 ([0036](0036-frontend-student-self-view.md)).
- **Headings**: the full-page error/404 titles are now `<h1>` (via `FullPageMessage`), not `<p>`.

### 4. Consistent error UX (401/403/404/409/502)

Audited and confirmed **complete + consistent**: `401` → never a toast (`AuthGuard`/proxy
refresh-and-retry, then `/login`); `403`/`409`/`502` → toast the `{detail}`; `404` → an in-page
"not found" `EmptyState` on detail screens **or** the new router `not-found.tsx` for unmatched URLs;
an unhandled render fault → `error.tsx`. No screen surfaces a raw error — every catch funnels through
`isApiError(err) ? err.message : "Something went wrong"`, and `client.ts` builds `ApiError` from
`{detail}`. F7 closed the two remaining holes (render fault, bad URL).

### 5. Responsive + cleanup

- The **Lightbox** side panel now caps height + scrolls on mobile (`max-h-[45vh] overflow-y-auto
  sm:…`) so a long appearances list can't push Download/Close off-screen. Data tables already scroll
  (the `Table` primitive wraps in `overflow-x-auto`).
- The masonry vertical gutter is defined **once** on the `PhotoGrid` container (`[&>*]:mb-2`), matching
  `GridSkeleton`, instead of on each tile.
- Deleted the now-dead **`ComingSoon`** component (F6 replaced its last user); wrote **`README.md`**
  (architecture, design system, dev setup, the gate, the phase map).

## Alternatives rejected

- **`unstable_retry`** in the error boundaries — the 16.2 docs nudge toward it, but the `unstable_`
  prefix is a maintenance risk and this app's boundaries catch render faults (not RSC-data fetches),
  where `reset`'s re-render is correct. Documented the choice in `error.tsx`.
- **A per-page `aria-live`/`aria-busy` wrapper** for every load swap — disproportionate churn (~11
  screens) for a best-effort gain; `role="alert"` on the error states (the part that matters) +
  `role="status"` on the skeleton deliver the value at the primitive level.
- **A dark-mode toggle** — the tokens are dark-ready (CSS vars), but a themed toggle + persistence
  isn't "near-free"; deferred.

## What this phase does NOT do (deferred, documented)

- **Live smoke** across F2–F6 is still pending a running stack (Docker down) — the highest-value being
  F5's (real `matches` + signed downloads).
- Dark-mode toggle (above); a service-side error logger (the boundary `console.error`s for now); OTel
  tracing / rate limiting / security headers are backend concerns ([0029](0029-hardening.md)).

## Testing

- Gate green (`eslint` + `tsc --noEmit` + `next build`, Node 22) after each review round. No backend
  change.
- **2× review→fix loop.** R1 (correctness) — **no blockers**; the agent verified the error-boundary
  contracts against the *installed* Next 16.2.9 docs (client `error.tsx`/root `global-error`/server
  `not-found`), the drawer focus/Esc/close-on-navigate, and the roving radiogroup. Fixed: the drawer
  now closes on resize-to-desktop; documented the `reset` choice. R2 (design/a11y/error-UX) — **no
  blockers**; the error-UX audit came back complete. Fixed: unified the three error surfaces (+ `<h1>`),
  the Lightbox mobile scroll, the redundant mobile logout, the `role="alert"` error announcements +
  `role="status"` skeleton, and the masonry gutter.
- Live smoke **pending** the stack (above).

## Files

- **New:** `app/{error,not-found,global-error}.tsx`; `components/ui/full-page-message.tsx`;
  `README.md`.
- **Changed:** `components/ui/app-shell.tsx` (mobile drawer + shared NavList/UserFooter, resize-close,
  dropped redundant logout); `components/gallery/filter-chips.tsx` (roving radiogroup);
  `components/ui/{empty-state,full-page-error}.tsx`; `components/gallery/{grid-skeleton,photo-grid,
  photo-tile,lightbox}.tsx`; the 13 error-`EmptyState` screens (`role="alert"`).
- **Deleted:** `components/coming-soon.tsx`. **No migration, no backend change, no new dep.**
