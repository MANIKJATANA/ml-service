# 0032 — Frontend platform admin: schools + admins (Phase F2)

**Date:** 2026-07-12
**Status:** Accepted

## Context

F1 ([0031](0031-frontend-auth-and-shell.md)) delivered auth + the shell + the primitive seed.
**F2 is the first feature area** on top of it: the **platform admin** flows — onboard schools and
provision their administrators. It also brings the first **data `Table`** and the Radix **`Dialog`**
(deferred from F1). Architecture is unchanged from [0030](0030-frontend-architecture-and-design-system.md)/
0031 (BFF, client-side SWR, per-persona route groups); this record covers what F2 adds and refines.

## Decisions

### 1. Screens (platform_admin only, `school:manage`)

- **`(platform)/schools`** — a `Table` of schools (name → detail link, `max_teachers`, status pill,
  created date) with loading / empty / error states, plus a **Create-school `Dialog`** (name, max_teachers
  1–100,000). On success it revalidates the `"schools"` SWR key, toasts, and closes.
- **`(platform)/schools/[schoolId]`** — school detail (status, max_teachers, created) with a `Breadcrumb`
  and an **Add-administrator `Dialog`** (email + a **visible temporary password** the platform admin sets and
  relays; the admin is provisioned `must_change_password=true`). A 404 is shown distinctly from a generic
  error (and suppresses the pointless Retry).
- **No "list a school's admins" endpoint exists**, so the detail page is add-only: the success toast is the
  confirmation and there's nothing to revalidate. (A future backend `GET /v1/schools/{id}/admins` — additive,
  read-only — would let us list them; not requested for F2 to keep it frontend-only.)

### 2. New primitives (`components/ui`)

- **`dialog.tsx`** — Radix Dialog (scrim `bg-ink/50`, `rounded-modal` panel, `shadow-md`, `text-display-md`
  title). Radix supplies focus-trap/return, Esc/scrim close, and the `aria-labelledby`/`aria-describedby`
  wiring; a `sr-only` Description fallback satisfies Radix when none is passed. Controlled `open`; forms
  **reset on close** (`handleOpenChange`). First real use of the Radix dep planned since F1.
- **`table.tsx`** — composable `Table`/`Header`/`Body`/`Row`/`Head`/`Cell`; quiet muted header, hairline
  rows, `scope="col"` headers, sans **tabular** numerics (`text-tabular tabular-nums`, matching Stripe's
  `tnum`-on-sans — **not** a monospace family).
- **`breadcrumb.tsx`** — `<nav aria-label>` + `aria-current="page"` on the trailing crumb.

### 3. App-wide SWR defaults (refinement)

Introduced `components/swr-provider.tsx` — one `<SWRConfig value={{ shouldRetryOnError: false,
revalidateOnFocus: false }}>` at the root layout (wrapping `ToastProvider`). Each screen's explicit **Retry**
button is now the single retry path, so error states are stable. The per-hook options on `useMe` (F1) were
removed in favor of this global; `useSchools`/`useSchool` inherit it.

### 4. Backend-unreachable → clean 502 (bug fix)

`app/api/v1/[...path]/route.ts` previously let a thrown backend `fetch` (backend down) bubble to an
unhandled 500. Wrapped the backend calls in a try/catch that returns `502 {detail:"Service unavailable"}` —
matching the auth handlers. (Found while attempting the F2 smoke against a stopped backend.)

### 5. Data layer

`lib/api/types.ts` gains `SchoolResponse`/`SchoolStatus` (active|suspended; ISO-string timestamps);
`endpoints.ts` gains `listSchools`/`createSchool`/`getSchool`/`createSchoolAdmin` (path params
`encodeURIComponent`-encoded); `lib/hooks/use-schools.ts` (`useSchools`, `useSchool`); `lib/utils.ts`
gains `formatDate` (guards `Invalid Date`). `max_teachers` is integer-guarded client-side
(`parseInt` + range) with `type="number" inputMode="numeric" step={1}`.

## Alternatives rejected

- **A shared `FormDialog` abstraction** for the two dialogs — their bodies (fields/validation/revalidation)
  differ enough that at N=2 an abstraction obscures more than it saves; revisit if a third near-identical
  dialog appears.
- **A backend admin-list endpoint for F2** — deferred; F2 stays frontend-only (no backend change).
- **Monospace numerics** in the table — diverges from both references (Stripe uses `tnum` on the sans body;
  Linear reserves mono for code). Sans tabular instead.

## What this phase does NOT do (deferred, documented)

- The **live smoke was not run** — Docker Desktop (hence the backend + DB) was down when F2 landed. The
  schools flow reuses the exact BFF path smoke-validated in F1; **run the create/list/add-admin smoke once
  the stack is up.**
- No admin-list endpoint/UI (above); mobile nav drawer (still — first flagged F1); long-name truncation in
  the table cell / breadcrumb (a Breadcrumb `min-w-0`/`truncate` hardening); `autoComplete` on the temp
  password (verify browser behaviour in the smoke before changing from `off`).

## Testing

- Gate green (`eslint` + `tsc --noEmit` + `next build`, Node 22) after each review round.
- **2× review→fix loop:** R1 (correctness/data-flow) — no blockers; confirmed the 502 fix scoping; fixed the
  SWR retry/focus defaults, integer-guarded `max_teachers`, `formatDate` guard, dialog reset-on-close.
  R2 (design/a11y/edge) — no blockers; added `scope="col"`, switched the numeric cell to sans tabular
  (list/detail consistency), added `inputMode="numeric"`.
- Live smoke **pending** the backend (see above).

## Files

- **New:** `app/(platform)/schools/[schoolId]/page.tsx`; `components/ui/{dialog,table,breadcrumb}.tsx`;
  `components/swr-provider.tsx`; `lib/hooks/use-schools.ts`.
- **Changed:** `app/(platform)/schools/page.tsx` (was the F1 placeholder); `lib/api/{types,endpoints}.ts`;
  `lib/utils.ts`; `lib/hooks/use-me.ts` + `app/layout.tsx` (global SWRConfig); `app/api/v1/[...path]/route.ts`
  (502 fix); `package.json` (`@radix-ui/react-dialog`). **No migration, no backend change.**
