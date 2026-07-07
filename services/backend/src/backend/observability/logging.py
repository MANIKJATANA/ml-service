"""Structured logging via structlog (mirrors the ML service's configuration).

:func:`configure_logging` routes stdlib ``logging`` through structlog so the
libraries we depend on (uvicorn, sqlalchemy) share one pipeline. Output is JSON by
default (for Loki/OTel collectors); set ``json_output=False`` for human-readable
console logs in local dev.

Idempotent: safe to call from the API lifespan (and any worker entrypoint).
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure structlog + the stdlib root logger to emit structured records."""
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Bridge stdlib logging (uvicorn/sqlalchemy + our own logging.* calls) into the
    # same sink. ExtraAdder pulls `extra={...}` fields into the event dict, and
    # format_exc_info renders `log.exception(...)` tracebacks.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                *shared_processors,
                structlog.stdlib.ExtraAdder(),
            ],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.format_exc_info,
                renderer,
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(log_level)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger (thin wrapper for call-site clarity)."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
