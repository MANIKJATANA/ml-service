# 0074 — Product Build BP21b: Error truthfulness

- **Date:** 2026-08-16
- **Status:** implemented (gate green; 2× review loop clean)
- **Phase:** the second & **final** slice of **BP21 (Say what it does)** — Round-3 review theme **M**
  ([0064](0064-product-review-round-3-ux.md)), after 21a copy/explainer
  ([0073](0073-product-build-BP21a-say-what-it-does.md)). Redeems Round-3 findings **R3-S3-06/08/09/10**.
  **FE + the BFF proxy only — no backend/ML change, no migration, no new dependency, no new permission.**
  **Completes BP21.**

## Context

Four error states misdirected the user (the review's theme-M error half):

- **Mid-session 401 → a dead Retry (R3-S3-08).** When a session expired mid-session, a *data* page's SWR read
  got a 401, and — because the app-wide `SWRConfig` disables retry + focus-revalidation ([0032](0032-frontend-platform-admin.md))
  — nothing re-checked the user, so `AuthGuard` never learned the session was dead. The page just showed
  "Something went wrong" over a **Retry that could never succeed** (the 401 recurs). (The BFF already clears the
  cookies on an unrecoverable 401, so the session really was dead — only the *redirect* was missing.)
- **422 → "Unprocessable Entity" (R3-S3-09).** `bffFetch` only understood a **string** `detail`; FastAPI's
  request-validation 422 sends `detail: [{loc, msg, …}]`, so a bad email surfaced the raw status text.
- **429 `Retry-After` stripped (R3-S3-10).** The BFF proxy forwarded **only** `content-type`, dropping the
  `Retry-After` header BP8c ([0051](0051-product-build-BP8c-rate-limiting-security-headers.md)) sends — so a
  throttle read as a generic error with no "try again in N".
- **Raw 500 (R3-S3-06).** A backend 5xx toasted its raw `str(exc)` (`detail`) rather than a calm generic line.

## Decision

1. **A shared 401 interceptor** (`components/swr-provider.tsx`). An SWR `onError(error, key)`: on an `ApiError` with
   `status === 401` from **any key except `"auth/me"`**, call `mutate("auth/me")`. That revalidates `useMe`, which
   gets the 401 (cookies already cleared) → `AuthGuard` redirects to `/login?reason=expired` (BP18a's "you were
   signed out" cue) — instead of a dead Retry. The `"auth/me"` key is skipped so the interceptor **cannot loop**
   (the AuthGuard already handles `useMe`'s own 401 directly).
2. **Parse 422 field errors** (`lib/api/client.ts`). A new `errorMessage()` handles the response by status:
   `parseValidationDetail()` + `fieldFromLoc()` turn `detail: [{loc:["body","email"], msg:"value is not a valid
   email address"}]` into **"Email: value is not a valid email address"** (field humanized from `loc`, capped at 3
   with a `; …` overflow, every hostile input guarded so it never throws inside the error path).
3. **Forward + humanize 429.** The BFF proxy (`app/api/v1/[...path]/route.ts`) now forwards **`Retry-After`**
   alongside `content-type`; `bffFetch` reads it (`parseRetryAfter`) onto a new optional **`ApiError.retryAfter`**
   and folds it into the message via `formatRetryAfter()` → **"Too many requests — please try again in N
   seconds/minutes."** (or "in a moment" when absent).
4. **Generic 5xx.** `errorMessage()` returns **"Something went wrong on our end — please try again in a moment."**
   for `status >= 500` — never the raw backend exception. 4xx keep their actionable `detail` (401/403/404/409
   messages are unchanged, so "Invalid credentials" etc. still show).

## Why

- **Put the fixes in one place.** Folding the message logic into `bffFetch` means all ~40 `toast(isApiError(err) ?
  err.message : …)` call sites get the truthful message with **zero call-site changes** — the single source of
  truth for "what does this status mean to a user".
- **Redirect, don't retry, a dead session.** A client-visible 401 only happens after the BFF's transparent
  refresh-retry has already failed, so it unambiguously means "signed out" — the right response is the login
  bounce, not a Retry. Driving it through `mutate("auth/me")` reuses the existing `AuthGuard` redirect rather than
  adding a second redirect path.
- **Humanize where the header lives.** `Retry-After` is the backend's, so the BFF forwards it and the client
  formats it — no new backend surface.

## Consequences / honest limits (documented)

- **FE + BFF proxy only; no backend/ML/migration/dependency/permission change.** No `.env` surface change.
- **`Retry-After` is parsed as integer seconds only.** The RFC-7231 HTTP-date form degrades to the "in a moment"
  fallback — BP8c never sends a date, so this is a spec-completeness gap, not a live one.
- **Internal field names *could* surface in a 422** (`student_group_id` → "Student group id"). In practice the only
  user-typed field that can 422 is **email** (HTML5 email validation is lenient, pydantic `EmailStr` is strict →
  "Email: value is not a valid email address" — the case that reads best); id/path fields are app-controlled opaque
  strings never typed into a form, and `max_teachers` is client-guarded before the call. So a raw internal name is
  reachable only via a hand-crafted request, not any real form.
- **The 5xx path discards the backend `detail` by design** (generic message) — any actionable 5xx text (e.g. a
  maintenance note) is lost; acceptable since the app never sends user-actionable 5xx detail.
- **Three co-existing phrasings for a backend fault** — `AuthGuard` "Couldn't reach the server.", the ~15 page
  `EmptyState`s "Something went wrong reaching the server.", and this toast — surface in different contexts (full-page
  boundary / inline empty-state / transient toast), so a user rarely sees two at once. The first two predate BP21;
  a full string-consolidation is a candidate follow-up, not this slice.
- **A one-render staleness window** before the 401 redirect (the data page briefly shows its own error while
  `useMe` revalidates) is inherent to async revalidation and harmless — its Retry re-hits the BFF, re-fires the
  interceptor.
- Verified: FE **lint + tsc + `next build` green**; no BE/ML suite delta (frontend-only). **2× review→fix loop —
  no blockers.** **R1** (correctness/control-flow) traced all four fixes against the SWR 2.4.2 runtime source, the
  BFF refresh boundary, the backend `Retry-After` emitter (integer seconds, always ≥1), and all ~40 `ApiError`
  consumers: loop-safety, the redirect (incl. the stale-`data` case), the refresh boundary (only truly-dead
  sessions reach the client as 401; login/change-password aren't SWR so they're unaffected), the 422 parse safety,
  and no regressions — **zero findings**, one harmless nit (the staleness window). **R2** (copy/a11y/consistency/
  edges) — no blockers → confirmed the reachable 422 (email) reads best, the error toasts ride an accessible
  `role="alert"` channel, and the 401 is a silent redirect (no error flash); applied **one fix** (minute-format a
  large `Retry-After` so it never reads "in 3600 seconds") and produced the honest-limits list above.
- **BP21 (Say what it does) is now complete (a, b).** **Next:** the owner picks the next Round-3 phase — the
  recommended order continues **BP20** (the arrival moment) → BP22/BP25/BP23/BP24
  ([`product/07`](../product/07-improvement-roadmap-round-3.md)); a phase starts only on owner pick + scope
  re-confirm.
