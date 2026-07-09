# Scripts

Helper scripts for working with the repo.

| Script | What it does |
|---|---|
| `up.ps1` | Brings the stack up in Docker. First it **advisory-checks `.env` against `.env.example`** (warns which keys are missing; never blocks). Backing services (Postgres + Redis) start **detached and keep running**; then **pending DB migrations run** (one-shot `migrate` service, `alembic upgrade head` — aborts if they fail); then the app services (frontend + backend + ml-service) run **attached in the foreground**. Press **Ctrl+C** to stop only the app services — Postgres/Redis stay up so you keep DB/queue state. Fails fast if the Docker daemon isn't running. `-Detached` runs the apps in the background too; `-NoBuild` skips rebuilding app images. |
| `sync-env.ps1` | Adds any active `KEY=` present in **`.env.example` but missing from `.env`** (carrying the example's default/placeholder), and prints exactly which keys it added. Never overwrites existing `.env` values or real secrets; ignores commented example keys. `-Check` is a dry run that only reports the missing keys (used by `up.ps1`). |

Run from anywhere — the scripts `cd` to the repo root themselves:

```powershell
.\scripts\up.ps1            # infra in background; apps in foreground (Ctrl+C stops apps)
.\scripts\up.ps1 -Detached  # everything in the background
docker compose down         # stop everything, including Postgres + Redis
```
