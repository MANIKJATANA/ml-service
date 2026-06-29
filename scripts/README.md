# Scripts

Helper scripts for working with the repo.

| Script | What it does |
|---|---|
| `up.ps1` | Brings the whole stack up in Docker (`docker compose up --build`). Fails fast if the Docker daemon isn't running. Use `-Detached` to run in the background, `-NoBuild` to skip rebuilding. |

Run from anywhere — the scripts `cd` to the repo root themselves:

```powershell
.\scripts\up.ps1
.\scripts\up.ps1 -Detached
```
