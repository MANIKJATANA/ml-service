"""Enqueue producer-contract test (decisions/0022, 0027).

Guards the coupling 0022 flagged: the backend must XADD *exactly* the two string fields
the ML worker decodes for an event job. A rename on either side would make the ML worker
dead-letter the job — so this also cross-checks the field set against the ML worker's own
event-job field tuple.
"""

from __future__ import annotations

from backend.adapters.queue.inproc_producer import InProcEventJobProducer
from backend.adapters.queue.redis_producer import encode_job
from backend.domain.models import EventJob

# Cross-check the contract directly against the consumer's field tuple.
from ml_service.adapters.queue.redis_streams import _JOB_FIELDS as ML_JOB_FIELDS

_JOB = EventJob(school_id="s1", event_id="e1")


def test_encode_emits_exactly_the_contract_fields() -> None:
    assert set(encode_job(_JOB)) == {"school_id", "event_id"}


def test_encode_matches_ml_worker_field_set() -> None:
    # The producer and the ML consumer must agree on the exact field names.
    assert set(encode_job(_JOB)) == set(ML_JOB_FIELDS)


def test_encode_values_are_all_strings() -> None:
    fields = encode_job(_JOB)
    assert all(isinstance(v, str) for v in fields.values())


def test_encode_carries_field_values() -> None:
    fields = encode_job(_JOB)
    assert fields["school_id"] == "s1"
    assert fields["event_id"] == "e1"


async def test_inproc_producer_records_jobs() -> None:
    producer = InProcEventJobProducer()
    await producer.enqueue(_JOB)
    assert producer.jobs == [_JOB]
