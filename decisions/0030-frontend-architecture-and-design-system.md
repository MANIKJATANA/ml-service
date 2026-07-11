# 0030 — Frontend architecture + design system (Phase F0)

**Date:** 2026-07-12
**Status:** Accepted

## Context

The backend is v1 feature-complete + hardened ([0022](0022-backend-architecture-and-scope.md)–[0029](0029-hardening.md)).
The **frontend** (`frontend/`) is still a bare **Next.js 16.2.9 + React 19** scaffold — config + deps
only, no `app/` UI, styling, or components. This record opens the frontend build-out and locks its
architecture + design system **before** any UI is written (docs-first), so the feature phases (F1–F7)
have a fixed foundation to build on.

Two hard inputs shape everything:

1. **`frontend/AGENTS.md`** warns that this is **not** the Next.js in training data — Next 16 has real
   breaking changes. The bundled docs (`frontend/node_modules/next/dist/docs/01-app/`) are the source of
   truth; the landmines are enumerated below and honored throughout.
2. **Design direction "Crisp modern SaaS (light)"** (owner-approved) with three reference specs in
   `frontend/design/` (fetched via the getdesign CLI): `linear.DESIGN.md` (dashboard precision),
   `pinterest.DESIGN.md` (image-first masonry gallery), `stripe.DESIGN.md` (forms + trust). These files
   are the **binding source of truth for the look** — the tokens below are synthesized from them, and
   every phase's review checks fidelity against the files, not just this summary.

The app has four personas → four UX surfaces: **platform_admin** (onboard schools), **school_admin /
teacher** (staff, students, events, media, galleries), **student** (self-view of own photos).

## Decisions

### 1. Auth + rendering: Backend-for-Frontend (BFF) with HttpOnly cookies

The browser never sees the FastAPI origin or the JWTs. Next **Route Handlers** under `app/api/**` proxy
to the backend, attaching the access token from an **HttpOnly / Secure / SameSite=Lax** cookie.

- `app/api/auth/{login,logout,refresh,change-password,me}/route.ts` — the only place cookies are set/cleared.
  `login` proxies `POST /v1/auth/login` and stores `access` (900 s) + `refresh` (14 d) as HttpOnly cookies.
- `app/api/[...path]/route.ts` — authenticated catch-all: attaches the access token; on a `401` it calls
  `POST /v1/auth/refresh`, rotates both cookies, and retries once; on refresh failure it clears cookies → 401.
- `proxy.ts` (repo `frontend/` root — **not** `middleware.ts`, renamed in Next 16) — a cheap **optimistic**
  gate only: cookie-present + coarse role→route-group redirect, and `must_change_password` → `/change-password`.
  **Real authorization stays on FastAPI** (the docs explicitly warn not to rely on the proxy for authz).
- Server-only base **`BFF_BACKEND_ORIGIN`** (dev `http://localhost:8001`, compose `http://backend:8000`) —
  **never** a `NEXT_PUBLIC_*`. The browser only ever calls same-origin `/api/**`.

**Rendering is hybrid:** Server Components for non-polled first paint (read the cookie via `await cookies()`,
call the backend server-side — data-complete first paint, no token in the browser); Client Components + SWR
for anything interactive or polled (forms, uploader, PhotoGrid/Lightbox, the status poller, toasts).

Why over a client-token SPA: transparent + safe refresh (the 14-day refresh token lives in a cookie JS can
never read, vs. localStorage = XSS-exfiltratable); no CORS/preflight; session survives reload; matches the
Next-16 idiom. **Photo bytes still transfer browser↔Supabase directly** (upload via signed URL, download via
signed URL) — the BFF only fronts the small FastAPI JSON calls, never the heavy path.

### 2. Data layer: hand-written typed client + SWR

- `lib/api/`: `types.ts` (hand-maintained TS mirrors of every request/response + enums — the surface is
  small/stable and there is no wired OpenAPI export, so no codegen), `client.ts` (`bffFetch` → `/api/**`,
  throwing a typed `ApiError` from `{detail}` + status, 204-safe), `endpoints.ts` (one typed fn per route),
  `server.ts` (server-side variant that reads the cookie and calls the backend directly), `errors.ts`.
- **SWR** for fetch/revalidate/**polling** — `useEventStatus` uses `refreshInterval` and **stops once
  `processing_status === "completed"`**; mutations call the endpoint then `mutate()` affected keys.
- Uploads use **`XMLHttpRequest`** (not `fetch`) for progress events.

### 3. Styling: Tailwind v4 `@theme` + CSS vars — light-only now, dark-ready

- Setup: `tailwindcss` + `@tailwindcss/postcss` (dev), `postcss.config.mjs`, `app/globals.css` =
  `@import "tailwindcss";` + a `@theme {}` block mapping the tokens (and `--font-sans`/`--font-mono` to the
  Geist vars already declared in `layout.tsx`). The CRA `@media (prefers-color-scheme: dark)` auto-dark block
  is **removed** (the OS must not flip our colors). `cn()` (`clsx` + `tailwind-merge`) in `lib/utils.ts`.
- Tokens live as CSS vars under `:root`; `@theme` references them, so a future `[data-theme="dark"]` override
  needs no component churn.

### 4. Design tokens (synthesized from the three `frontend/design/*.DESIGN.md` files)

- **Color:** canvas `#ffffff`, surface `#f8f9fa`, surface-2 `#f0f2f7`, hairline `#e3e8ef`,
  hairline-strong `#c9d1de` (resting input border — *not* the focus ring); ink `#0d1729`,
  ink-secondary `#5a6578` (small meta text), ink-muted `#8890a0` (placeholder / large-only — sub-AA as
  small text); **accent `#6366f1`** (hover `#4f46e5`, dark `#312e81`, on-accent `#ffffff`);
  **ring `#6366f1`** (= accent, the 2px `:focus-visible` ring). Semantic **base** values are for
  non-text/UI + large text only: success `#059669`, warning `#d97706`, error `#dc2626`, info `#0284c7`
  — each paired with a **`-soft` tint + `-strong` text shade** for AA-compliant StatusPill/Toast labels
  (e.g. success `#ecfdf5`/`#047857`); neutral pill = surface-2 + ink-secondary.
- **Type:** Geist Sans + Geist Mono (already wired). display-xl 48 / lg 32 / md 24 (negative tracking),
  headline 20, body 14, body-sm 12, tabular 13 (`font-feature-settings:"tnum"` for numeric columns).
- **Spacing** 4px base (4/8/12/16/24/32/48/64). **Radius** button/input 8, card 12, modal 16, pill 9999.
  **Shadow** sm `0 1px 2px rgba(13,23,41,.05)`, md `0 4px 12px rgba(13,23,41,.08)`. 1px hairline borders;
  2px accent focus ring. Reconciliations (Linear dark→our light base; Pinterest red→our indigo; three
  proprietary display fonts→Geist) are documented per the synthesis.

### 5. Folder structure — per-persona App-Router route groups

```
frontend/
  proxy.ts                          # optimistic auth gate (F1)
  postcss.config.mjs                # (F0)
  app/
    globals.css                     # @import tailwindcss + @theme (F0)
    layout.tsx                      # Geist fonts (exists) + ToastProvider (F1)
    page.tsx                        # role redirect (F1)
    (auth)/{login,change-password}/
    (platform)/schools/{page,[schoolId]}                         # F2
    (school)/{dashboard,staff,students/[studentId],
             events/[eventId]/{upload,gallery},photos/[mediaId]} # F3–F5
    (student)/me/{events,gallery}                                # F6
    api/auth/*/route.ts  +  api/[...path]/route.ts               # BFF (F1)
  lib/{api,hooks,auth,utils.ts}
  components/{ui/, <feature>/}
```

Route groups `(name)` scope layouts/nav per persona without changing URLs and let `proxy.ts` gate by prefix.

### 6. Component inventory (`components/ui`, built incrementally, owned code)

Radix (headless) primitives styled entirely with our tokens (shadcn/ui-style) supply focus-trap/keyboard/ARIA
for Dialog/Select/Tabs/Toast. Kit: Button, Input/Field, Select, Card, Table/DataTable (tabular `tnum`),
Dialog+Confirm, Toast+provider, Badge/StatusPill (maps `enrollment_status`/`processing_status`/`needs_review`),
Tabs, `StudentAvatar` (optional `photoUrl` — real thumbnails wire in later), Skeleton, EmptyState,
AppShell/Nav/Sidebar (role-filtered), PageHeader/Breadcrumb, Spinner/ProgressBar, **PhotoGrid** (CSS masonry,
12px gutters, image-bleed, `next/image`, lazy per-tile download URL), **Lightbox** (full-screen, ←/→/Esc,
download), **Uploader** (drag-drop, ≤30 MB + type guard, XHR progress; single in F3, multi in F4).

### 7. Phase plan + per-phase Definition of Done

**F0** foundations (this record + toolchain, no UI) · **F1** auth + app shell + primitive seed · **F2**
platform admin (schools) · **F3** staff + students + enrollment + single uploader · **F4** events + media
upload + processing/status polling · **F5** galleries + download (PhotoGrid + Lightbox) · **F6** student
self-view · **F7** polish + hardening.

Every phase: (1) gate green = `npm run lint` + `tsc --noEmit` + `npm run build`; (2) new env vars → root
`.env.example`; (3) its own decision record; (4) **mandatory 2× review→fix loop** (R1 correctness /
auth / data-flow / error-handling / Next-16 async APIs; R2 edge cases / **design fidelity vs. the
`frontend/design/*.DESIGN.md` files** / a11y / simplification), re-greening the gate after each round;
(5) manual smoke path vs. the running local backend; (6) **STOP for owner approval.** No test framework in v1
(bare-minimum automated gate; rigor comes from the review loop). Never commit/push unless asked.

### 8. One additive backend change (approved once — additive, read-only)

`email: str` on `StudentResponse` (`api/schemas/students.py` + the student read so the linked login's email is
available). **Why:** the staff Students UI should show the login email set at create time; the read model
returns `name` but not `email`. **Not a flow change** — a single added output field; request bodies, enums,
auth, and the create/enroll/delete flow are untouched. Lands in F3. *(Deferred, not requested: `created_at`
on `UserResponse`, per-event counts — derived or omitted by the FE.)*

## Next.js 16 landmines honored

`params`/`searchParams`/`cookies()`/`headers()` are **async — always awaited**; middleware is **`proxy.ts`**;
`fetch` is **uncached by default** (use `next:{revalidate}` or `<Suspense>`); Turbopack is the default bundler;
`output:"standalone"` stays; path alias `@/*` → `frontend/` root (no `src/`); `next/image` needs
`images.remotePatterns` for `*.supabase.co`; fonts via `next/font/google` (Geist, already wired).

## Alternatives rejected

- **Client-token SPA** — simpler to start, but exposes the 14-day refresh token to XSS, forces CORS
  everywhere, loses the session on reload, and fights Next-16 idioms.
- **Codegen API client / runtime OpenAPI** — the surface is small and stable; a hand-maintained typed client
  is lighter and clearer, guarded by TS + the review loop.
- **Hand-rolled a11y primitives** — Radix gives correct focus-trap/keyboard/ARIA for free; hand-rolling is
  slower and easy to get subtly wrong.
- **A fourth design reference** — three focused references keep the system coherent; more dilutes it.

## What F0 delivers (this phase)

This record; the Tailwind v4 + PostCSS pipeline (`postcss.config.mjs`, `globals.css` `@theme` tokens, auto-dark
removed); deps `tailwindcss` + `@tailwindcss/postcss` + `clsx` + `tailwind-merge`; `lib/utils.ts` (`cn()`);
`next.config.ts` Supabase image host; corrected `layout.tsx` metadata; removal of the CRA `page.tsx` /
`page.module.css` boilerplate; and `BFF_BACKEND_ORIGIN` documented in root `.env.example`. **No UI, no BFF, no
components yet** — those begin in F1.

## Follow-up (2026-07-12): frontend Docker build

`docker compose up --build` surfaced two frontend-image issues (independent of app code):

- **`npm ci` cross-platform lock drift.** F0 added Tailwind v4, whose `oxide` native binary pulls a
  wasm fallback with `@emnapi/*` transitive optional deps. The `package-lock.json` generated on the
  Windows dev host (npm 10.9) omits some of those, so `npm ci` (exact-sync) fails on the linux
  `node:24-slim` image (`EUSAGE: Missing @emnapi/... from lock file`). Fix: the deps stage now uses
  **`npm install --no-audit --no-fund`** (reconciles instead of exact-sync) — robust as more FE deps
  get added from Windows. Reproducibility trade-off accepted for a Windows-dev/linux-deploy setup.
- **Missing `public/`.** The Dockerfile's `COPY --from=builder /app/public ./public` had no source
  (create-next-app's `public/` was absent here). Added `frontend/public/.gitkeep`.

The full image now builds (deps → `next build` → standalone runner). Deferred: add the frontend image
to CI's `docker-build` job so this stays green (small hardening follow-up).
