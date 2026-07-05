"""Inference worker entrypoint — the real job loop.

Builds the composition-root container, constructs the inference service (loading
the detector/embedder models) and the job queue, then runs the consume loop
until interrupted. Model construction is offloaded to a thread so we don't block
the loop during startup; the container is disposed on exit.

Each replica must use a unique consumer name within the group for at-least-once
recovery — set ``ML_QUEUE_CONSUMER`` per replica in deployment.
"""

from __future__ import annotations

import asyncio
import logging

from ml_service.wiring.container import Container
from ml_service.wiring.settings import settings
from ml_service.workers.runner import WorkerRunner

log = logging.getLogger(__name__)


async def _run(container: Container) -> None:
    queue = container.job_queue()
    # Loading the models blocks — keep it off the loop during startup.
    service = await asyncio.to_thread(container.inference_service)
    runner = WorkerRunner(
        queue,
        service,
        max_retries=settings.worker_max_retries,
        backoff_base_s=settings.worker_backoff_base_s,
    )
    log.info(
        "inference worker starting",
        extra={"stream": settings.queue_stream, "consumer": settings.queue_consumer},
    )
    await runner.run()


async def _amain(container: Container) -> None:
    # Run and dispose on the SAME event loop — the async engine/Redis client are
    # bound to it, so cleanup must not happen under a second asyncio.run().
    try:
        await _run(container)
    finally:
        await container.aclose()


def main() -> None:
    logging.basicConfig(level=settings.log_level)
    container = Container(settings)
    try:
        asyncio.run(_amain(container))
    except KeyboardInterrupt:
        log.info("inference worker stopping")


if __name__ == "__main__":
    main()
