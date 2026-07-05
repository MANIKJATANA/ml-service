"""OpenTelemetry tracing setup (architecture §11).

Tracing is **opt-in**: :func:`configure_tracing` installs an SDK
``TracerProvider`` with an OTLP/HTTP exporter only when an endpoint is given
(``ML_OTEL_EXPORTER_OTLP_ENDPOINT``). With no endpoint the global API returns a
no-op tracer, so :func:`span` is always safe to call — instrumented code paths
carry zero overhead when tracing is disabled.

v1 instruments at the **service-call boundary** (the worker's ``process`` and the
enroll route) rather than wrapping every port call: the orchestration/domain
layers stay import-pure, and the adapters aren't rewritten. Per-adapter spans are
a documented follow-up (see decisions/0017).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.trace import Tracer

_TRACER_NAME = "ml_service"
_configured = False


def configure_tracing(
    service_name: str, *, otlp_endpoint: str = "", console: bool = False
) -> None:
    """Install a real TracerProvider when an OTLP endpoint (or console) is set.

    Idempotent and lazy in its imports: the SDK/exporter are only imported when
    tracing is actually enabled, keeping the no-tracing path free of setup cost.
    """
    global _configured
    if _configured or not (otlp_endpoint or console):
        return

    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=otlp_endpoint)))
    if console:
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer() -> Tracer:
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def span(name: str, **attributes: object) -> Iterator[trace.Span]:
    """Start a span; a no-op when tracing is unconfigured (default provider)."""
    with get_tracer().start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)  # type: ignore[arg-type]
        yield current
