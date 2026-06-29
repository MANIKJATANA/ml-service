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

## Notes

More scripts (DB migrate, seed, lint-all, etc.) can be added here as needed.
