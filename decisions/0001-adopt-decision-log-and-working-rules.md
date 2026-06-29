# 0001 — Adopt decision log and working rules

**Date:** 2026-06-30
**Status:** Accepted

## Context

The repo is in the design phase. The owner wants the reasoning behind every change preserved and a consistent set of working conventions for anyone (human or Claude) operating in the repo.

## Decision

- All changes and non-trivial decisions are recorded in `decisions/` (this folder), one file per decision, indexed in `decisions/README.md`.
- `CLAUDE.md` is kept up to date alongside any change that affects architecture, commands, or conventions.
- Nothing is pushed to a remote (no `git push`, no PRs) until explicitly requested.
- After making changes, review the work and fix self-introduced issues before reporting completion.
- `.env` / secrets files are never read; secrets are never stored.

## Why

Keeps decisions auditable and the onboarding doc trustworthy, and keeps control over what leaves the local machine.
