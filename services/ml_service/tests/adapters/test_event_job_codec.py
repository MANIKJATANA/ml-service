"""Pure encode/decode of the event-job Redis payload (decisions/0027).

No Redis needed — ``_encode``/``_decode`` are static. Guards the DLQ-malformed branch
(a missing field → ``None`` → dead-letter) the backend producer's contract warns about.
"""

from __future__ import annotations

from ml_service.adapters.queue.redis_streams import RedisStreamsJobQueue
from ml_service.domain.models import EventJob

_JOB = EventJob(school_id="s1", event_id="e1")


def test_encode_emits_exactly_the_contract_fields() -> None:
    assert set(RedisStreamsJobQueue._encode(_JOB)) == {"school_id", "event_id"}


def test_encode_decode_roundtrip() -> None:
    assert RedisStreamsJobQueue._decode(RedisStreamsJobQueue._encode(_JOB)) == _JOB


def test_decode_missing_field_is_none() -> None:
    # A missing field -> None -> the queue dead-letters the message as malformed.
    assert RedisStreamsJobQueue._decode({"school_id": "s1"}) is None
    assert RedisStreamsJobQueue._decode({"event_id": "e1"}) is None
    assert RedisStreamsJobQueue._decode({}) is None


def test_decode_tolerates_bytes_keys_and_values() -> None:
    assert RedisStreamsJobQueue._decode({b"school_id": b"s1", b"event_id": b"e1"}) == _JOB
