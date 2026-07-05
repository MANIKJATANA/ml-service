"""FastAPI dependency wiring → the composition root (:mod:`wiring.container`).

The container is a process-wide singleton (built from ``settings`` once). The
enrollment service — which loads the detector/embedder models on first use — is
built lazily off the request path via a threadpool so the event loop never
blocks on model I/O. Tests inject a service by overriding
``get_enrollment_service`` in ``app.dependency_overrides``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from starlette.concurrency import run_in_threadpool

from ml_service.orchestration.enrollment import EnrollmentService
from ml_service.wiring.container import Container
from ml_service.wiring.settings import settings


@lru_cache(maxsize=1)
def get_container() -> Container:
    """The process-wide container (memoized)."""
    return Container(settings)


async def get_enrollment_service(
    container: Annotated[Container, Depends(get_container)],
) -> EnrollmentService:
    # First call loads the models (blocking) — keep it off the event loop.
    return await run_in_threadpool(container.enrollment_service)


EnrollmentServiceDep = Annotated[EnrollmentService, Depends(get_enrollment_service)]
