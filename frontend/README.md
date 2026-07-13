# Frontend

The web UI for the multi-tenant face-recognition photo-distribution service. **Next.js 16
(App Router) + React 19 + Tailwind v4 + SWR**, with owned Radix-based primitives. It talks
to the FastAPI backend through a **BFF** (backend-for-frontend) layer so the browser never
holds a JWT.

Architecture + design decisions are recorded in [`decisions/`](../decisions) (`0030`–`0037`);
this README is the operational overview.

## Architecture

### BFF + HttpOnly cookies (auth)

The browser only ever calls **same-origin `/api/**`** — it never sees a token or the backend
origin.

- `app/api/auth/*` — the only place cookies are set/cleared. `login` proxies the backend and
  stores the `access` (short-lived) + `refresh` (long-lived) JWTs as **HttpOnly / Secure /
  SameSite=Lax** cookies. `login` returns only `must_change_password` to the browser.
- `app/api/v1/[...path]` — a transparent proxy: it attaches the access token, and on a `401`
  it calls the refresh endpoint, rotates the cookies, and retries once. An unrecoverable
  `401` clears the session; a `403` never does. A backend that's down surfaces as a clean
  `502`.
- `proxy.ts` (Next middleware) — an **optimistic** cookie-presence gate only (no token
  decode). Real authz is the backend's job (RBAC → 403); role/`must_change_password` routing
  lives in the client `AuthGuard` shell.
- Server-only `BFF_BACKEND_ORIGIN` — **never** a `NEXT_PUBLIC_*` var.

### Route groups (per persona)

`app/` is split by persona, each group's `layout.tsx` wrapping an `AuthGuard` that resolves
the user and enforces the allowed role(s):

| Group | Roles | Screens |
|---|---|---|
| `(auth)` | — | login, change-password |
| `(platform)` | `platform_admin` | schools + admins |
| `(school)` | `school_admin`, `teacher` | staff, students, events, upload, galleries, photo detail |
| `(student)` | `student` | "My Photos" (self-scoped) |

`AuthGuard` redirects a disallowed role to its home; a same-group screen that is
admin-only (e.g. staff) uses a lightweight `RoleGate` on top.

### Data layer (`lib/`)

- `lib/api/` — `client.ts` (`bffFetch`, typed `ApiError` from `{detail}`), `endpoints.ts`
  (one typed fn per route), `types.ts` (hand-maintained mirrors of the backend schemas +
  enums), `errors.ts`, `upload.ts`, `download.ts`.
- `lib/hooks/` — SWR hooks. A root `SWRConfig` sets `shouldRetryOnError: false` +
  `revalidateOnFocus: false`; each screen's **Retry** button is the single retry path.
  `useEventStatus` polls with an auto-stopping `refreshInterval`.

### Media: direct-to-Supabase

Photo **bytes never pass through the BFF**. The backend mints a signed upload/download URL;
the browser **XHR PUTs** the bytes straight to Supabase (with progress) and then registers
the object, or fetches the blob for download. See `lib/api/upload.ts` / `download.ts`.

## Design system

Tailwind v4 CSS-first `@theme` tokens in `app/globals.css`, synthesized from the reference
specs in `design/*.DESIGN.md` (Linear = dashboard precision, Pinterest = masonry gallery,
Stripe = forms). Direction: **"Crisp modern SaaS (light)"** — light canvas, a single indigo
accent, image-first galleries. Geist Sans/Mono. Light-only today, **dark-ready** (all tokens
are CSS vars). Primitives are **owned** in `components/ui` (Radix supplies focus-trap /
keyboard / ARIA for Dialog, Tabs); the gallery lives in `components/gallery`.

## Develop

Requires **Node ≥ 20.9** (Next 16). The shell often defaults to too-old Node 18 — use the
pinned version:

```bash
nvm use 22            # (see .nvmrc)
npm install
npm run dev           # http://localhost:3000
```

Point the BFF at a running backend via `frontend/.env.local`:

```
BFF_BACKEND_ORIGIN=http://127.0.0.1:8001
```

(Use `127.0.0.1`, not `localhost` — Node's `fetch` resolves `localhost` to IPv6 `::1`, which
a Docker-published port refuses. In compose it's `http://backend:8000`.) The full env surface
is documented in the repo-root [`.env.example`](../.env.example); server-only vars are never
`NEXT_PUBLIC_*`.

## Gate

Every change must pass:

```bash
npm run lint          # eslint (eslint-config-next)
npx tsc --noEmit      # types
npm run build         # next build (Turbopack)
```

There is no unit-test framework in v1 — rigor comes from a **2× code-review→fix loop** per
phase (see the decision records) plus a manual smoke path.

## Phase map

The build was delivered in reviewed, docs-first phases, one decision record each:

| Phase | What | Record |
|---|---|---|
| F0 | Foundations: tokens, toolchain, architecture | [0030](../decisions/0030-frontend-architecture-and-design-system.md) |
| F1 | Auth (BFF) + app shell + primitive seed | [0031](../decisions/0031-frontend-auth-and-shell.md) |
| F2 | Platform admin: schools + admins | [0032](../decisions/0032-frontend-platform-admin.md) |
| F3 | Staff + students + ML enrollment | [0033](../decisions/0033-frontend-staff-and-students.md) |
| F4 | Events + media upload + processing | [0034](../decisions/0034-frontend-events-and-processing.md) |
| F5 | Galleries + download | [0035](../decisions/0035-frontend-galleries-and-download.md) |
| F6 | Student self-view | [0036](../decisions/0036-frontend-student-self-view.md) |
| F7 | Polish + hardening | [0037](../decisions/0037-frontend-polish-and-hardening.md) |

## Layout

```
frontend/
  proxy.ts                     # optimistic auth gate (Next middleware)
  app/
    error.tsx / not-found.tsx / global-error.tsx
    layout.tsx                 # providers (SWR, Toast) + fonts + metadata
    globals.css                # @theme tokens
    api/auth/*  api/v1/[...path]   # the BFF
    (auth) (platform) (school) (student)/   # persona route groups
  components/
    ui/                        # owned primitives (Button, Dialog, Table, Tabs, …)
    gallery/                   # PhotoGrid, Lightbox, SignedImage, …
    auth-guard.tsx  role-gate.tsx  app-shell.tsx
  lib/
    api/  hooks/  auth/  events/  students/  utils.ts
  design/                      # *.DESIGN.md reference specs
```
