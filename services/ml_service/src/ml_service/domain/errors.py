"""Domain error hierarchy — pure, no third-party imports."""

from __future__ import annotations


class MLServiceError(Exception):
    """Base class for all ML-service domain errors."""


class EnrollmentError(MLServiceError):
    """An enrollment-pipeline failure."""


class InferenceError(MLServiceError):
    """An inference-pipeline failure."""


class MediaFetchError(MLServiceError):
    """Media bytes could not be fetched from the media store."""


class MediaDecodeError(InferenceError):
    """Media bytes were fetched but could not be decoded (corrupt/unsupported).

    Permanent, not retryable — distinct from the transient ``MediaFetchError``.
    Architecture §8.4: a corrupt video is marked complete, not retried in a loop.
    """


class EmbeddingVersionMismatch(MLServiceError):
    """A loaded index's embedding-model version != the configured embedder
    (architecture §7.3) — never search a stale-model index."""


class LockAcquisitionError(MLServiceError):
    """Could not acquire the per-school FAISS write lock (Option B / Redis, decisions/0052)
    — the lock backend is unreachable or the wait timed out. Fail-loud: an unlocked write
    under multi-replica risks a lost enrollment, so the enroll fails (retryable) instead."""


class ConfigurationError(MLServiceError):
    """Invalid or missing wiring/configuration."""
