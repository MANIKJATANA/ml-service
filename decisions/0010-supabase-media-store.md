# 0010 — Supabase Storage as the default MediaStore

**Date:** 2026-07-02
**Status:** Accepted

## Context

Architecture §6 names Azure Blob as the default `MediaStore` (matching the
owner's prior stack). The owner directed that **Supabase Storage** be the default
media backing for this service ("by default storage use supabase for media
stuff"). Per the CLAUDE.md rule, this divergence from the locked architecture is
recorded rather than applied silently.

## Decision

- The default `MediaStore` adapter is **`SupabaseMediaStore`**
  (`adapters/media_store/supabase_storage.py`), used for both event media and
  reference photos. It accepts a Supabase project URL, an access key (a secret,
  injected by wiring from the environment — never committed or stored in code),
  and a bucket. It resolves `http(s)` URIs via httpx and bucket object paths via
  the Supabase Storage client.
- **`LocalFsMediaStore`** (`adapters/media_store/local_fs.py`) is the dev/test +
  offline-CI adapter (a real, architecture-sanctioned adapter, not a mock).
- **Scope: media only.** The metadata DB stays on our own Postgres; FAISS index
  files default to a shared volume in dev and may use Supabase Storage in prod
  via the pluggable index store (see [0011](0011-faiss-adapter-lifecycle.md)).
- Azure Blob / S3 remain trivial future registry additions behind the same port
  (NFR-2); nothing in `orchestration/` changes.

## Why

- Direct owner instruction; Supabase is the platform's storage.
- Reuses the single `MediaStore` port for both pipelines, so enrollment and
  inference share one media path.

## Alternatives rejected

- **Azure Blob default** (architecture §6) — not the owner's storage.
- **A separate reference-photo ingestion path** — the media port already covers
  fetching bytes; no second path needed (see [0009](0009-enrollment-contract.md)).
