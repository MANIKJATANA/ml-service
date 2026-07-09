# 0024 — Backend auth (roll-our-own JWT) + RBAC seam (Phase 2)

**Date:** 2026-07-09
**Status:** Accepted

## Context

Phase 1 ([0023](0023-backend-db-schema.md)) stood up the backend foundations:
settings, the DB + its own Alembic chain, the `schools`/`users` tables, the
ports/registry/container skeleton, and health probes. Every feature phase that
follows ([0025](0022-backend-architecture-and-scope.md)–`0029`) is behind
authentication and role checks, so auth is the first real capability. The owner
locked the shape in [0022](0022-backend-architecture-and-scope.md): **roll-our-own
JWT** (email + password, argon2, self-issued access + refresh tokens; no Supabase
Auth), and **static-now / extensible-later RBAC** where every check routes through a
single `PermissionResolver.permissions_for(user)` seam.

This decision records the Phase 2 build: how passwords are hashed, how tokens are
issued/verified, the RBAC model, the request-scoped auth dependencies, the auth
routes, the `users` schema/port extensions, and the platform-admin bootstrap.

## Decisions

### Password hashing and tokens are ports, not helpers

To keep `services/` import-pure (the layering invariant: no `passlib`/`jwt` in
`domain`/`services`, enforced by `tests/test_layering.py`), the two crypto
concerns are **ports with adapters**, exactly like the repositories:

- **`PasswordHasher`** port — `hash` / `verify` / `needs_rehash`. Adapter:
  `Argon2PasswordHasher` (`adapters/security/argon2_hasher.py`) over passlib's
  `CryptContext(schemes=["argon2"])`. `verify` swallows malformed-hash errors and
  returns `False` (never leaks a 500 on a bad stored hash).
- **`TokenService`** port — `issue_pair(user) -> TokenPair` and
  `decode(token, *, expected_type) -> TokenClaims`. Adapter: `JwtTokenService`
  (`adapters/security/jwt_tokens.py`) over PyJWT (HS256). Access tokens carry
  `sub, role, school_id, type="access", iss, iat, exp`; refresh tokens carry the
  minimal `sub, type="refresh", iss, iat, exp` (identity is reloaded from the DB on
  refresh, so a refresh token needs no role/tenant claim). Decode verifies
  signature + `iss` + `exp` and asserts the `type` matches what the caller expects;
  any failure (bad signature, expired, wrong type) raises `AuthenticationError`.

`AuthService` (`services/auth_service.py`) depends only on these ports plus
`UserRepository`, so it is unit-testable with fakes and touches no crypto lib.

### RBAC: a `Permission` enum + `ROLE_PERMISSIONS`, behind one resolver

`domain/permissions.py` (pure) defines a `Permission` enum and the hardcoded
`ROLE_PERMISSIONS: dict[Role, frozenset[Permission]]`. Permissions are **seeded from
the locked product surface** in [0022](0022-backend-architecture-and-scope.md) and
grow per feature phase:

| Permission | platform_admin | school_admin | teacher | student |
|---|:-:|:-:|:-:|:-:|
| `school:manage` (onboard/list schools) | ✓ | | | |
| `staff:manage` (create/list teachers) | | ✓ | | |
| `student:manage` | | ✓ | ✓ | |
| `event:manage` | | ✓ | ✓ | |
| `media:upload` | | ✓ | ✓ | |
| `job:status:view` | | ✓ | ✓ | |
| `gallery:view_all` | | ✓ | ✓ | |
| `gallery:view_own` | | | | ✓ |

Every check routes through the **`PermissionResolver`** port. v1 ships
`StaticPermissionResolver` (`permissions_for(user)` → `ROLE_PERMISSIONS[user.role]`);
a later `DbPermissionResolver` overlays per-school override rows with **zero
call-site change**, satisfying the owner's "define at our level now, hand the choice
to school admins later." **RBAC is authorization only** — it answers *may this role
do X*. **Tenant isolation** (*may this user touch this school's/student's rows*) is a
separate, query-layer concern enforced when feature repos take `school_id` /
`student_id` arguments (0022); Phase 2 has no tenant-scoped resource yet.

### Request-scoped dependencies (`api/deps.py`)

- `get_current_user` — reads the `Authorization: Bearer <token>` header
  (`HTTPBearer(auto_error=False)`), decodes it as an **access** token, reloads the
  user by `sub`, and rejects (`AuthenticationError` → 401) when the header is
  missing/malformed, the token is invalid/expired, the user no longer exists, or the
  user is `disabled`. Reloading (rather than trusting token claims) means a disabled
  or deleted account loses access immediately, and role/tenant are always fresh.
- `require_permissions(*perms)` — a dependency **factory** returning a guard that
  resolves the caller's permissions via the container's `PermissionResolver` and
  raises `AuthorizationError` (→ 403) unless every required permission is granted.
  Feature routers in later phases mount it (`Depends(require_permissions(...))`).

Dependencies resolve the container via the process-wide `get_container()` singleton
(`backend/deps.py`), so they work under a bare `TestClient` without the lifespan —
matching the existing health/readyz behaviour.

### Routes (`api/routers/auth.py`, mounted under `/v1/auth`)

- `POST /v1/auth/login` `{email, password}` → `{access_token, refresh_token,
  token_type, expires_in, must_change_password}`. Invalid email **or** password
  yields the same generic 401 (no account enumeration); a `disabled` account is
  likewise a generic 401.
- `POST /v1/auth/refresh` `{refresh_token}` → a fresh token pair (reloads + revalidates the user).
- `POST /v1/auth/change-password` `{current_password, new_password}` (auth required)
  → 204; verifies the current password, stores the new argon2 hash, and clears
  `must_change_password`.
- `GET /v1/auth/me` (auth required) → the caller's public profile (never the hash).

### Schema + port extensions

- **Migration `0002`** (backend chain) adds `users.must_change_password boolean NOT
  NULL DEFAULT false`. Staff-created accounts and temp-password students
  ([0022](0022-backend-architecture-and-scope.md) forks 4–5) set it `true` in their
  phases; `login` surfaces it so the FE can force a change. Added to the ORM +
  `domain.User` in lockstep (working rule: schema changes go through migrations).
- **`UserRepository`** gains `must_change_password: bool = False` on `create` (so
  Phase 3/4 can provision temp-password accounts) and a
  `set_password(user_id, password_hash, *, must_change_password)` method (the only
  write path for `change-password`). Both land on the Postgres adapter.
- **Email is a case-insensitive identifier.** A pure `normalize_email` (strip +
  lower-case) is applied at the repository's write and read boundaries, so a user who
  registers as `Ops@X.io` logs in as `ops@x.io` and `uq_users_email` rejects
  case-variant duplicates (0023 deferred this here). v1 lower-cases the whole
  address; a `citext` column preserving display case is the documented scale-up.

### Settings additions (`BE_` env surface)

`jwt_secret: SecretStr` (default empty — **not** a hardcoded secret; the
`JwtTokenService` build raises `ConfigurationError` if it is empty, so a prod deploy
fails loud without a key while imports/tests that never build the token service stay
green), `jwt_algorithm="HS256"`, `jwt_issuer="backend"`,
`access_token_ttl_s=900` (15 min), `refresh_token_ttl_s=1209600` (14 days), and the
selectors `password_hasher_impl="argon2"`, `token_service_impl="jwt"`,
`permission_resolver_impl="static"`.

### Platform-admin bootstrap (`python -m backend.cli.bootstrap_admin`)

The first `platform_admin` (global, null `school_id`) is created by a management
command taking `--email` and an optional `--password` (prompted via `getpass` when
omitted, so it need never appear in shell history or a process listing) — **never
from `.env`** (0022 baked default). It builds the container, hashes the password, and
inserts the user; a duplicate email is reported and is a no-op.

### Dependencies added (`services/backend/pyproject.toml`)

`passlib[argon2]` (argon2-cffi), `pyjwt>=2.9`, `email-validator` (for `EmailStr` on
the login/create schemas). All install cross-platform (native Windows dev works).
`python-multipart` and `supabase`/`redis`/`httpx` remain deferred to the phases that
use them.

## Consequences

- The backend can authenticate users and gate routes; every later phase mounts
  `require_permissions(...)` and (where relevant) passes `school_id`/`student_id` to
  its repos for tenant isolation.
- The RBAC seam is real from day one: swapping `StaticPermissionResolver` for a
  `DbPermissionResolver` is a registry entry + a settings flag, no call-site edits.
- `jwt` and `passlib` join the layering blocklist (already listed in
  `test_layering.py` / `scripts/check.ps1`); services stay crypto-free.
- No feature routes yet — only `/v1/auth/*`. `require_permissions` is shipped and
  unit-tested here; its first route consumers arrive in Phase 3.

## Alternatives rejected

- **Password hashing / JWT as plain helper modules in `services/`** — rejected: it
  would pull `passlib`/`jwt` into a pure layer and break the layering invariant, and
  it would make `AuthService` hard to unit-test without crypto. Ports + adapters cost
  one Protocol each and keep the seam swappable.
- **Trusting role/school_id from the access-token claims** (no per-request DB
  reload) — rejected for v1: a stale token would keep a disabled/role-changed account
  alive until expiry. Reloading is one indexed PK lookup; correctness wins. (Revisit
  with a short access TTL + a denylist only if profiling demands it.)
- **A single long-lived token** (no refresh) — rejected: short access TTL + refresh
  limits the blast radius of a leaked access token without forcing frequent logins.
- **Encoding a hardcoded dev JWT secret as the default** — rejected (secret in code,
  against the working rules); empty default + fail-loud-on-build instead.
