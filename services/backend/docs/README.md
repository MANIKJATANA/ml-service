# Backend design docs

Living reference for the backend service (`services/backend/`) — the product's
"core system". Rationale for each decision lives in the repo-root `decisions/`
log (`0022`–`0029`); these docs are the "how it fits together" reference.

- [00-overview.md](00-overview.md) — what the backend is, the layered architecture,
  module map, data model, RBAC, API surface, ML integration, and the phase roadmap.

Docs are added as their phase lands:
- `01-data-model.md` — full backend schema + the ML tables/views it reads (Phase 1).
- `02-auth-rbac.md` — JWT auth + the permission model (Phase 2).
- `03-integration.md` — the ML enroll client, the Redis job producer, Supabase
  storage, and the shared-DB results reader (Phases 4–6).

The binding source of truth for the ML side is `ml-service-requirements.md` /
`ml-service-architecture.md` and the ML service's own `docs/`. The backend never
diverges from the ML integration contract recorded in [decisions/0022](../../../decisions/0022-backend-architecture-and-scope.md).
