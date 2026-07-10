"""In-process event-job producer — credential-free dev/test (decisions/0027).

Records enqueued event jobs in an in-memory list instead of touching Redis. The backend
has no consumer of its own (the ML worker consumes), so for offline dev this simply lets
the flow run without Redis. Selecting ``inproc`` + ``local_fs`` + ``fake`` runs the whole
backend with no Redis, Supabase, or ML service.
"""

from __future__ import annotations

from backend.domain.models import EventJob


class InProcEventJobProducer:
    """``EventJobProducer`` that appends jobs to an in-memory list."""

    def __init__(self) -> None:
        self.jobs: list[EventJob] = []

    async def enqueue(self, job: EventJob) -> None:
        self.jobs.append(job)
