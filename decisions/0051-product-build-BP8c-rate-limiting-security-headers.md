# 0051 — Product Build BP8c: Rate limiting + security headers

**Date:** 2026-07-23
**Status:** Accepted

## Context

Third slice of **BP8 (Ops & reliability)** (`product/03`; after BP8a/BP8b). Redeems the two items
[decisions/0029](decisions/0029-hardening.md) explicitly **deferred** ("rate limiting, security headers"). Fails lens
**X5/T7** (risk reduction): the API had **no throttle** — a runaway client or a login brute-force was unbounded — and
**no security headers** anywhere. Pure hardening: **backend + frontend; no migration, no ML change, on by default.**

**Owner scope calls (this session):** rate-limit keying = a **global** cap + a per-**`school_id`** (tenant) cap
(the backend sits behind the Next BFF, so it can't see the real client IP — per-IP is out; `school_id` is derived
**internally** from the JWT) + a stricter cap on `/v1/auth/*`; **security headers on BOTH** the frontend (browser-facing,
incl. a CSP) and the backend (defense-in-depth); **on by default**, a **pluggable store** (in-memory default, Redis
config-gated), **fail-open**.

## Decisions

### 1. Rate limiting — a `RateLimiter` port + a FastAPI middleware
A `RateLimiter` Protocol (`domain/ports.py`) — `acquire(key, *, limit, window_s) -> RateLimitResult{allowed,
retry_after_s}`, fixed-window — with two adapters behind `RATE_LIMITER_REGISTRY` (`memory`|`redis`): an
**`InMemoryRateLimiter`** (per-replica `key -> (window, count)`, atomic within the event loop, injectable clock) and a
**`RedisRateLimiter`** (`INCR`+`EXPIRE` per window in a MULTI/EXEC pipeline, wall-clock window so replicas align,
reuses `BE_REDIS_URL`). Both **fail-open** — a store error returns `allowed=True`; a limiter fault must never take the
API down. The middleware (`_install_rate_limit` in `main.py`) builds the limiter **once per app in `create_app`** (not
the process-global `lru_cache` container — so an in-memory limiter can't accumulate counts across a test suite's many
`create_app()` calls) and checks tiers per request: **global**, a stricter **auth** tier on `/v1/auth/*`, and — when a
**verified** access token is present — a per-**`school:{id}`** tier (`school_id` from a best-effort
`token_service().decode`, wrapped in `try/except` so a forged/refresh/empty-secret token simply skips the tier; an
unverified `school_id` is never trusted). First tier exceeded → **`429` + `Retry-After`** + a
`backend_rate_limit_rejections_total{scope}` metric (fixed scope set — cardinality-safe). Liveness/readiness/metrics
(`/healthz`, `/readyz`, `/metrics`) are **exempt** (a throttled probe would flap the deploy). The redis limiter is
closed on shutdown via `lifespan`.

**Middleware order** (`create_app`), outer→inner: **security-headers → CORS → rate-limit → metrics → routes**.
Rate-limit sits **inside CORS** (so preflight `OPTIONS` short-circuits at CORS, unthrottled) and **outside metrics** (a
429 is counted by its own rejection metric, never folded into the HTTP counter as `__unmatched__`); security-headers is
**outermost** so its headers land on the 429 + every error response.

### 2. Backend security headers — defense-in-depth
`_install_security_headers` (outermost, gated on `security_headers_enabled`) `setdefault`s on **every** response (so it
never clobbers `WWW-Authenticate`/`Retry-After`): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: no-referrer`, `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (a JSON API loads
nothing — a maximal CSP is safe), and — when `hsts_enabled` (**default off**; prod-behind-TLS turns it on) —
`Strict-Transport-Security`.

### 3. Frontend security headers — the browser-facing set (`next.config.ts` `headers()`)
Only Next talks to the browser (the backend is reached via the `/api` BFF proxy), so **these are the headers that
actually protect users**. `headers()` on `/:path*`: `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
strict-origin-when-cross-origin`, `Permissions-Policy`, `Cross-Origin-Opener-Policy: same-origin`, `HSTS` (browsers
ignore it over http, safe in dev), and a **CSP** sized to the app: `default-src 'self'`; `img/media/connect-src`
allowing Supabase (signed image/video + XHR upload/download) + `blob:`/`data:`; `frame-ancestors 'none'`,
`object-src 'none'`, `base-uri`/`form-action 'self'`; `script/style-src 'self' 'unsafe-inline'` with `'unsafe-eval'`
**dev-only** (React HMR uses eval; never in prod). New settings `BE_RATE_LIMIT_*` / `BE_SECURITY_HEADERS_ENABLED` /
`BE_HSTS_*` (+ a test-only `BE_TEST_REDIS_URL`) → all in `.env.example`.

## Honest limits (documented)

- **Fixed window, not sliding:** a client can burst up to **2× the limit** across a window boundary. Accepted for a
  coarse throttle; a sliding/token-bucket window is the scale-up (noted in the adapter docstring).
- **The auth tier is a single global bucket** (no client IP behind the BFF), shared across all schools' `/v1/auth/*`
  (incl. `refresh`). Default raised to **300/min** so real concurrent logins aren't locked out — a coarse brute-force
  ceiling, not per-attacker; **per-IP limiting belongs at the ingress/edge** (deferred).
- **The FE CSP leans on `frame-ancestors`/allow-lists** — the high-value, safe wins (clickjacking, MIME, referrer,
  transport, source restriction). `script-src` keeps `'unsafe-inline'` (no nonce infra); a **nonce-based strict CSP via
  `proxy.ts`** is the follow-up.
- **In-memory store is per-replica** (effective limit = N× under multiple replicas) — the **redis** impl is the
  cross-replica option (`BE_RATE_LIMIT_IMPL=redis`).

## Verification

- BE gate green: ruff + mypy + **full suite 385 passed / 26 skipped** — adapters (off-by-one, window reset, key
  independence, `retry_after ≤ window`, **always-on redis fail-open** on a mid-op `RedisError`) + a **gated real-Redis**
  round-trip + connect-failure fail-open (`BE_TEST_REDIS_URL`, unique short-lived keys — never a `FLUSH`); middleware
  (global 429 + `Retry-After`, the auth tier trips before global, per-school independence, probes/metrics **exempt**, a
  malformed `Authorization` header falls through to global without a 500, **fail-open** when the limiter raises, the
  rejection metric increments); security headers (present on 200 + error + the **429**, HSTS gated, disabled → absent).
- FE gate green: `tsc --noEmit` + `eslint` + `next build`; the CSP checked against the **installed** Next 16 docs
  (`'unsafe-eval'` dev-only, `headers()` `source: "/:path*"`). Live browser smoke (the CSP doesn't break hydration)
  pending a running stack, per prior FE phases.
- **2× review→fix loop** (two agents). **R1 (correctness/security/ordering): no blocker** — middleware order,
  verified-token decode, off-by-one, fail-open, and test isolation all confirmed sound; flagged the missing redis
  `aclose` + probe throttling. **R2 (edge/quality/config): no code blocker** — flagged the same `aclose` leak, the
  too-tight auth default, and the missing always-on redis-fail-open test. **Applied:** redis `aclose` on shutdown, the
  probe/metrics exemption, auth default 60→**300** (documented), the fixed-window-burst doc, `Cross-Origin-Opener-Policy`,
  and the extra tests.

## Follow-ups

**BP8d** multi-replica enrollment (Redis-lock Option B) · **BP8e** retention/erasure (per `product/03`). Optional BP8c
polish: a **nonce-based strict CSP** (`proxy.ts`), **per-IP** auth limiting at the ingress (or forwarding a trusted
`X-Forwarded-For`), a **sliding-window** limiter, and setting `BE_RATE_LIMIT_IMPL=redis` + `BE_HSTS_ENABLED=true` in the
prod compose/manifests.
