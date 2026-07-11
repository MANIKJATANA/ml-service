"""Prometheus metrics for the backend HTTP API (mirrors the ML service's module).

One request counter + one latency histogram, recorded by the HTTP middleware in
:mod:`backend.main`. Labels are **low-cardinality only** — the HTTP method, the matched
**route template** (e.g. ``/v1/events/{event_id}/students``, *never* the concrete path
``/v1/events/abc-123/students``), and the status code. Both label dimensions are bounded
so a hostile client can't grow the series count: the ``route`` is the template (unmatched
requests collapse to ``__unmatched__`` in the middleware) and ``method`` is clamped to the
registered HTTP verbs (``OTHER`` for anything else). Never label with a concrete
``student_id``/``media_id`` or the raw request path (unbounded → cardinality bomb,
mirrors requirements §13's note for the ML service).

The default registry is exposed at ``GET /metrics`` (see :mod:`backend.main`).
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

# The registered HTTP methods; anything else is folded to OTHER so a client sending
# arbitrary method tokens can't spawn unbounded `method=` series.
_KNOWN_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}
)

REQUESTS = Counter(
    "backend_http_requests_total",
    "HTTP requests handled, by method, route template, and status code.",
    ("method", "route", "status"),
)
REQUEST_LATENCY = Histogram(
    "backend_http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    ("method", "route"),
    # Coarse buckets spanning a fast health probe to a slow ML-backed gallery read.
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def record_request(method: str, route: str, status: int, duration_s: float) -> None:
    """Fold one finished HTTP request into the counter + latency histogram.

    ``method`` is clamped to the registered verbs and ``route`` is the matched route
    template — both bounded to keep the label cardinality safe (see module docstring).
    """
    method = method if method in _KNOWN_METHODS else "OTHER"
    REQUESTS.labels(method=method, route=route, status=str(status)).inc()
    REQUEST_LATENCY.labels(method=method, route=route).observe(duration_s)


def render_latest() -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for the ``/metrics`` scrape endpoint."""
    return generate_latest(), CONTENT_TYPE_LATEST
