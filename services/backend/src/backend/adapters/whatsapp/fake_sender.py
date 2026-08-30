"""In-proc ``WhatsAppSender`` — the default, credential-free adapter (W1).

A REAL, deterministic adapter (not a test mock): it records each call's kwargs in an
in-memory list and returns a ``WhatsAppReceipt`` with a synthetic ``fake-<uuid4>`` message
id. Selected by ``BE_WHATSAPP_SENDER_IMPL=fake`` (the default), so the backend runs W1's
config surface with no Gupshup account. W1 never actually invokes it (no send endpoint yet);
it exists so the sender is buildable + registry-resolvable, and W2 can call it in tests.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from backend.domain.models import WhatsAppReceipt


@dataclass(frozen=True, slots=True)
class SentImage:
    """One recorded ``send_image`` call (test/introspection convenience)."""

    to: str
    image_url: str
    template_name: str
    sender_number: str
    caption: str | None


class FakeWhatsAppSender:
    """Always-succeeds WhatsApp sender for credential-free local dev/tests."""

    def __init__(self) -> None:
        self.sent: list[SentImage] = []

    async def send_image(
        self,
        *,
        to: str,
        image_url: str,
        template_name: str,
        sender_number: str,
        caption: str | None = None,
    ) -> WhatsAppReceipt:
        self.sent.append(
            SentImage(
                to=to,
                image_url=image_url,
                template_name=template_name,
                sender_number=sender_number,
                caption=caption,
            )
        )
        return WhatsAppReceipt(provider_message_id=f"fake-{uuid.uuid4()}", to=to)
