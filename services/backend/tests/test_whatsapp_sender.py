"""The FakeWhatsAppSender adapter (W1).

A real, deterministic adapter (not a mock): it records each call and returns a receipt echoing
the recipient. W1 never invokes the sender from a service (no send endpoint yet — that is W2);
this just proves the adapter's shape.
"""

from __future__ import annotations

import pytest
from backend.adapters.whatsapp.fake_sender import FakeWhatsAppSender
from backend.adapters.whatsapp.gupshup_sender import _redact, _to_receipt
from backend.domain.models import WhatsAppReceipt


async def test_fake_sender_records_call_and_returns_receipt() -> None:
    sender = FakeWhatsAppSender()
    receipt = await sender.send_image(
        to="15551230000",
        image_url="https://downloads.test/events/s1/e1/m1",
        template_name="photo_notice",
        sender_number="15551234567",
        caption="Your event photos",
    )
    assert isinstance(receipt, WhatsAppReceipt)
    assert receipt.to == "15551230000"
    assert receipt.provider_message_id.startswith("fake-")
    # The call was recorded verbatim.
    assert len(sender.sent) == 1
    sent = sender.sent[0]
    assert sent.to == "15551230000"
    assert sent.image_url == "https://downloads.test/events/s1/e1/m1"
    assert sent.template_name == "photo_notice"
    assert sent.sender_number == "15551234567"
    assert sent.caption == "Your event photos"


async def test_fake_sender_distinct_message_ids_and_optional_caption() -> None:
    sender = FakeWhatsAppSender()
    r1 = await sender.send_image(
        to="1", image_url="u", template_name="t", sender_number="s"
    )
    r2 = await sender.send_image(
        to="2", image_url="u", template_name="t", sender_number="s"
    )
    assert r1.provider_message_id != r2.provider_message_id  # unique per send
    assert sender.sent[0].caption is None  # caption defaults to None
    assert len(sender.sent) == 2


# The one Gupshup line that's testable without a live account: parsing the success body into a
# receipt. (The HTTP call itself is provider-doc-dependent and covered by the integration smoke.)
@pytest.mark.parametrize(
    ("payload", "expected_id"),
    [
        ({"messageId": "wamid.ABC"}, "wamid.ABC"),  # Gupshup's only id field (camelCase)
        # The docs-confirmed success shape: {"status":"submitted","messageId":"<uuid>"}.
        ({"status": "submitted", "messageId": "ee4a68a0-1203"}, "ee4a68a0-1203"),
        ({"message_id": "snake_123"}, ""),  # snake_case is NOT a real Gupshup field -> empty
        ({"status": "submitted"}, ""),  # a dict with no id field -> empty
        (["not", "a", "dict"], ""),  # a non-dict body -> empty, no crash
        ("plain string", ""),  # a non-dict body -> empty
    ],
)
def test_gupshup_to_receipt_parses_message_id(payload: object, expected_id: str) -> None:
    receipt = _to_receipt(payload, to="15551230000")
    assert isinstance(receipt, WhatsAppReceipt)
    assert receipt.provider_message_id == expected_id
    assert receipt.to == "15551230000"


# W2: the send path is live, so a failed send must not leak the recipient number into the
# UpstreamError. _redact keeps only the last 4 digits.
@pytest.mark.parametrize(
    ("number", "expected"),
    [
        ("15551234567", "*******4567"),  # a full number → all but last 4 masked
        ("1234", "****"),  # exactly 4 → fully masked (never expose < 4-digit tail)
        ("99", "**"),  # short → fully masked
        ("", ""),
    ],
)
def test_redact_masks_all_but_last_four(number: str, expected: str) -> None:
    out = _redact(number)
    assert out == expected
    # The full number never appears in its own redaction (unless it's ≤4 digits, fully masked).
    if len(number) > 4:
        assert number not in out
