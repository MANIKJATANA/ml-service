# 0031 — Frontend auth + app shell + primitive seed (Phase F1)

**Date:** 2026-07-12
**Status:** Accepted

## Context

[0030](0030-frontend-architecture-and-design-system.md) locked the frontend architecture
and design system (docs + toolchain, no UI). **F1 is the first real UI**: it puts login,
the authenticated app shell, and the seed of the `components/ui` kit on screen, wired to the
running FastAPI backend through the BFF. It realizes the auth/rendering and component
decisions from 0030; the notes below record where F1 refined them.

## Decisions

### 1. BFF auth handlers + HttpOnly cookie session

- `app/api/auth/{login,logout,refresh,change-password}/route.ts` are the FE-owned cookie
  managers. `login` proxies `POST /v1/auth/login`, then stores `access` (maxAge = `expires_in`,
  ~900s) + `refresh` (14d) as **HttpOnly, SameSite=Lax, `Secure` in prod only** cookies
  (`lib/auth/cookies.ts`). **`login` returns only `{ must_change_password }` — the JWTs never
  reach the browser.** `logout` expires both cookies (204). `change-password` forwards with the
  access-token Bearer; on 204 the client re-fetches `/me`.
- `Secure` is gated to prod so cookies work over `http://` in local dev but are `Secure` in prod.

### 2. Transparent authenticated proxy with refresh-and-retry

- `app/api/v1/[...path]/route.ts` — the browser calls same-origin `/api/v1/<path>`; the handler
  attaches the access-token Bearer and forwards to `${BACKEND}/v1/<path>` (query preserved). On a
  **401 it refreshes once** (`POST /v1/auth/refresh` with the refresh cookie), rotates both cookies,
  and retries; on an **unrecoverable 401 it clears the session** so the next navigation is bounced to
  `/login`. A **403 (wrong role) does NOT clear cookies** — it's a valid session lacking permission.
  Cookies are rotated only when the refresh returns **both** tokens. The incoming `Cookie` header is
  **not** forwarded to the backend (only `Authorization` + `content-type`). `GET`/`HEAD` send no body.
- `/me` and all data calls ride this proxy (e.g. the client calls `/api/v1/auth/me`).

### 3. `proxy.ts` = optimistic presence gate only

Per the Next 16 docs ("don't rely on proxy for authz; keep it to optimistic checks"), `proxy.ts`
does a cheap **cookie-presence** check: no session + protected path → `/login`; has session + `/login`
→ `/`. **No token decode, no network.** Real authorization is the backend's job (RBAC → 403); **role
and `must_change_password` routing happen in the shell** (§4), not the proxy. The matcher skips
`/api`, Next internals, and any dotted static path.

### 4. Rendering: client data-fetching via the BFF + SWR (server.ts deferred)

0030 planned a hybrid with some server-side fetching. F1 fetches authed data **client-side** via the
BFF proxy + **SWR** (`useMe`, stable key `"auth/me"`), because a Server Component can't set cookies
mid-render, so it can't transparently refresh an expired access token — the BFF route handler can.
`lib/api/server.ts` is therefore **deferred** to the first phase that genuinely server-renders authed
data. `components/auth-guard.tsx` is the client boundary each route group wraps: it resolves `/me`,
enforces role + `must_change_password` (redirecting), and renders the shell. A **backend 5xx/network
error is treated as "retry", not "logged out"** (only a 401 → `/login`) so a downed backend can't loop
`/`↔`/login`. Login/change-password/logout each invalidate the SWR `auth/me` cache to avoid stale-user
loops.

### 5. Component-kit seed (`components/ui`)

Seeded: Button (`cva` variants), Input, Field, Card, Toast (+provider), Spinner/FullPageSpinner,
FullPageError, Skeleton, EmptyState, StatusPill, PageHeader, AppShell (role-filtered sidebar + mobile
topbar). All token-driven with `focus-visible` rings; `Field` wires hint/error to the control via
`aria-describedby`; error toasts use `role="alert"`.
- **Toast is a custom `aria-live` implementation, not Radix Toast** (Radix Toast is heavier than a
  simple provider needs). **Radix is still the plan for Dialog/Select/Tabs** — the first, **Dialog**, is
  **deferred to F2** (its first real use is the add-admin modal), so no Radix dep lands in F1.

### 6. Screens + navigable shell

`(auth)/login` + `(auth)/change-password` (client forms → the BFF, per-field validation that clears on
edit); root `app/page.tsx` role-redirect; per-persona group layouts (`(platform)`/`(school)`/`(student)`)
each guarding by role via `AuthGuard`; a real `(school)/dashboard`; and **`ComingSoon` placeholders** for
`/schools`, `/staff`, `/students`, `/events`, `/me/events` so the shell is **fully navigable from F1**
(each later phase replaces its placeholder). Homes: platform_admin→`/schools`, school_admin/teacher→
`/dashboard`, student→`/me/events`.

### 7. Design calls

The **primary Button** and **active sidebar item** use **`accent-hover` (#4f46e5)**, not `accent`
(#6366f1): white-on-`#6366f1` is 4.47:1 (a hair under AA); `#4f46e5` is 6.29:1 and still the single-indigo
CTA (darkens further on hover). `accent` (#6366f1) remains the accent hue for focus rings. Destructive
button uses `text-on-accent` (token, not a raw `text-white`).

### 8. Config

Deps: `swr`, `lucide-react`, `class-variance-authority`. **`BFF_BACKEND_ORIGIN` defaults to
`http://127.0.0.1:8001`** for host dev — the IPv4 literal, because Node's `fetch` resolves `localhost`
to IPv6 `::1` first, which Docker Desktop's published port may refuse (`ECONNREFUSED`) even though curl
works. Compose still sets `http://backend:8000`.

## Alternatives rejected

- **Client-token SPA / tokens in JS** — rejected in 0030 (XSS-exfiltratable refresh token). The BFF keeps
  JWTs server-only.
- **Refreshing tokens in `proxy.ts`** — the docs warn against network in the proxy; refresh lives in the
  `/api/v1` route handler (which can set cookies), keeping the proxy fast + optimistic.
- **Radix Toast** — heavier than needed; a custom `aria-live` region suffices. Radix stays for Dialog/etc.

## What this phase does NOT do (deferred, documented)

- **Mobile navigation drawer** — the sidebar is `hidden sm:flex`; on mobile there's only a logout button.
  Acceptable for F1 (every destination is a `ComingSoon` placeholder), but **the first phase shipping real
  mobile-reachable pages (F2/F3) must add a hamburger drawer** or mobile users are stranded.
- `lib/api/server.ts` (server-side authed fetch); Radix **Dialog** (F2); voluntary change-password from a
  settings screen; consolidating the `AuthGuard`/root redirect logic into one hook; a toast-count cap;
  `EmptyState`/`FullPageError` titles as headings.

## Testing

- Gate green (ruff n/a — FE: `eslint` + `tsc --noEmit` + `next build`) under Node 22, after each review round.
- **Live curl smoke against the running backend:** login → 200 (+`access`/`refresh` cookies), `/me` → 200
  (real user via the BFF Bearer), wrong password → 401 `{detail}`, `/me` no cookie → 401, logout → 204,
  post-logout `/me` → 401, `proxy.ts` gate → 307 `/dashboard`→`/login`.
- **2× review→fix loop:** R1 (security/correctness/data-flow) — no blockers; fixed logout cache
  invalidation, backend-5xx-not-logout, content-type-only-with-body, both-token rotation, toast timer
  cleanup, matcher. R2 (design/a11y/edge) — no blockers; fixed `aria-describedby`, error-toast `role`,
  per-field change-password validation, the accent-contrast calls, token consistency.
- The smoke also surfaced two environment fixes now committed: the `127.0.0.1` default (§8), and a note
  that `next build` then `next dev` in the same dir needs a `.next` wipe (dev-only, not code).

## Files

- **New (BFF/auth):** `lib/api/{types,errors,client,endpoints}.ts`, `lib/auth/{backend,cookies,routes}.ts`,
  `lib/hooks/use-me.ts`, `app/api/auth/{login,logout,refresh,change-password}/route.ts`,
  `app/api/v1/[...path]/route.ts`, `proxy.ts`.
- **New (UI):** `components/ui/{button,input,field,card,toast,spinner,skeleton,empty-state,status-pill,page-header,app-shell,full-page-error}.tsx`,
  `components/{auth-guard,coming-soon}.tsx`.
- **New (screens):** `app/(auth)/{layout,login/page,change-password/page}.tsx`, group layouts +
  `dashboard` + the `ComingSoon` pages; `app/page.tsx` (root redirect).
- **Changed:** `app/layout.tsx` (`ToastProvider`); `.env.example` (`BFF_BACKEND_ORIGIN` → 127.0.0.1);
  `package.json` (deps). **No migration, no backend change** (the additive `email` field is F3).
