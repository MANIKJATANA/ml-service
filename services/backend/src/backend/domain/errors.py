"""Backend domain error hierarchy — pure, no third-party imports.

The API maps these to HTTP status codes centrally (``api`` layer), so services and
repositories raise domain errors rather than HTTP exceptions.
"""

from __future__ import annotations


class BackendError(Exception):
    """Base class for all backend domain errors."""


class NotFoundError(BackendError):
    """A requested resource does not exist (maps to HTTP 404)."""


class ConflictError(BackendError):
    """A uniqueness/state conflict, e.g. duplicate email (maps to HTTP 409)."""


class LimitExceededError(BackendError):
    """A quota/limit is reached, e.g. a school's teacher cap (maps to HTTP 409)."""


class ValidationError(BackendError):
    """Invalid input that business rules reject (maps to HTTP 400)."""


class ConfigurationError(BackendError):
    """Invalid or missing wiring/configuration (maps to HTTP 500)."""


class AuthenticationError(BackendError):
    """Missing/invalid credentials or token — who are you? (maps to HTTP 401)."""


class AuthorizationError(BackendError):
    """Authenticated but not permitted — you may not do this (maps to HTTP 403)."""


class UpstreamError(BackendError):
    """A downstream dependency (e.g. the ML service) failed or was unreachable
    (maps to HTTP 502). The request is well-formed; retrying later may succeed."""
