# Decision Log

Every change and decision made in this repo gets recorded here as a dated entry, so the reasoning behind the code is never lost.

## How to use

- One file per decision: `NNNN-short-slug.md` (zero-padded sequence, e.g. `0001-use-faiss-per-school.md`).
- Keep entries short: context, the decision, and why. Note alternatives rejected when relevant.
- Add a one-line pointer to the index below.
- When a decision is superseded, don't delete it — add a new entry and mark the old one `Superseded by NNNN`.

## Index

- [0001 — Adopt decision log and working rules](0001-adopt-decision-log-and-working-rules.md) — how decisions are recorded and the repo's working conventions.
- [0002 — Initialize git repository](0002-initialize-git-repo.md) — `git init` on `main`, secrets-safe `.gitignore`, initial commit.
- [0003 — Monorepo structure: FE + BE + ML service, 3 images](0003-monorepo-structure.md) — Next.js + FastAPI BE + ML service; uv workspace; `services/` + `frontend/` layout.
- [0004 — Scaffold the monorepo (uv workspace + 3 images)](0004-scaffold-monorepo.md) — runnable shells, health endpoints, Dockerfiles, compose with Postgres + Redis.
- [0005 — Add scripts/ folder with a stack-up helper](0005-add-scripts-folder.md) — `scripts/up.ps1` wraps `docker compose up --build`.
- [0006 — Temporary end-to-end wiring demo](0006-temporary-wiring-demo.md) — **TEMP** FE→BE→ML (HTTP + Redis) with Postgres writes from both; to be removed.
