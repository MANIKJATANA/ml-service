# 0002 — Initialize git repository

**Date:** 2026-06-30
**Status:** Accepted

## Context

The project was a plain folder of design docs with no version control. The owner asked to initialize the repo.

## Decision

- Ran `git init` with `main` as the default branch.
- Added a `.gitignore` covering secrets (`.env*`, keys, `secrets/`), Python artifacts, test/type-check caches, and ML model weights (downloaded, not source).
- Made an initial commit of the existing design docs, decision log, and `CLAUDE.md`.
- Per the working rules ([0001](0001-adopt-decision-log-and-working-rules.md)), nothing is pushed to a remote until explicitly requested.

## Why

Version control with a secrets-safe ignore list from commit one, before any code lands.
