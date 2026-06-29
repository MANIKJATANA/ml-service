# 0005 — Add scripts/ folder with a stack-up helper

**Date:** 2026-06-30
**Status:** Accepted

## Context

The owner wants a `scripts/` folder for repo helper scripts. For now, just one:
a script that brings everything up in Docker.

## Decision

- Added `scripts/` with `up.ps1` (PowerShell, since that's the dev box's primary
  shell) — a thin wrapper over `docker compose up --build` that cd's to the repo
  root and fails fast with a clear message if the Docker daemon isn't running.
  Flags: `-Detached` (background), `-NoBuild` (skip rebuild).
- Added `scripts/README.md` documenting it.

## Why

One obvious entrypoint to start the whole stack locally, with a friendly error
instead of a raw daemon-connection failure when Docker Desktop is down.

## Update (2026-06-30): Ctrl+C stops apps only

`up.ps1` now splits the stack:

- **Backing services** (Postgres, Redis) start **detached** and keep running.
- **App services** (frontend, backend, ml-service) run **attached in the
  foreground** with `--no-deps`, so **Ctrl+C stops only the apps** while Postgres/
  Redis stay up (no DB/queue state loss between restarts). `-Detached` runs the
  apps in the background too.

Also fixed while here:
- Removed `$ErrorActionPreference = 'Stop'` — in PS 5.1 it turned `docker compose`'s
  normal stderr progress into a terminating error and killed the run mid-build.
- Forced `COMPOSE_BAKE=false` — Compose's bake builder fails with
  `image "...": already exists` when rebuilding images already in Docker Desktop's
  containerd store; the classic builder works.
- Kept the script **pure ASCII** (em dashes broke string parsing in PS 5.1).

Verified on real Docker: full build + up exit 0, all 5 containers healthy, and
stopping the app services leaves Postgres + Redis running.

## Notes

More scripts (DB migrate, seed, lint-all, etc.) can be added here as needed.
