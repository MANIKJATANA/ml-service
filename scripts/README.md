# Scripts

Helper scripts for working with the repo.

| Script | What it does |
|---|---|
| `up.ps1` | Brings the stack up in Docker. Backing services (Postgres + Redis) start **detached and keep running**; then **pending DB migrations run** (one-shot `migrate` service, `alembic upgrade head` — aborts if they fail); then the app services (frontend + backend + ml-service) run **attached in the foreground**. Press **Ctrl+C** to stop only the app services — Postgres/Redis stay up so you keep DB/queue state. Fails fast if the Docker daemon isn't running. `-Detached` runs the apps in the background too; `-NoBuild` skips rebuilding app images. |

Run from anywhere — the scripts `cd` to the repo root themselves:

```powershell
.\scripts\up.ps1            # infra in background; apps in foreground (Ctrl+C stops apps)
.\scripts\up.ps1 -Detached  # everything in the background
docker compose down         # stop everything, including Postgres + Redis
```
