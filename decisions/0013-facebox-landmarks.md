# 0013 — Carry detector landmarks inside FaceBox

**Date:** 2026-07-02
**Status:** Accepted

## Context

ArcFace recognition requires the face crop to be **aligned** using the detector's
5-point landmarks (both eyes, nose, mouth corners) via `norm_crop`; skipping
alignment measurably degrades embedding quality. But the `FaceEmbedder.embed(
image_bytes, face_box)` port (req §9) passes only the `FaceBox` — there is no
channel for landmarks between detector and embedder.

## Decision

- Add an optional field to the domain model: `FaceBox.landmarks:
  tuple[tuple[float, float], ...] | None = None`. It is pure data (no third-party
  types); the SCRFD adapter populates it, and the ArcFace adapter converts it to
  its own array form for `norm_crop`.
- When `landmarks is None`, the embedder falls back to a plain bbox
  crop-and-resize (lower quality) — so any detector that yields no landmarks still
  works.
- The field is trailing with a default, so all Phase-1 constructions and tests are
  unaffected; the ports' method signatures are unchanged.

## Why

- Keeps the port contract intact (landmarks ride inside the value object the port
  already passes) while enabling correct ArcFace alignment.
- Detector/embedder stay in separate adapter modules (NFR-1); they communicate
  only through the domain `FaceBox`.

## Alternatives rejected

- **Re-detecting landmarks inside the embedder** — duplicates detection work and
  couples the embedder to a landmark model.
- **A new `AlignedFace` type or a wider `embed` signature** — a larger API change
  than a backward-compatible optional field.
