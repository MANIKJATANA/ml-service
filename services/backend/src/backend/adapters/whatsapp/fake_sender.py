"""In-proc ``WhatsAppSender`` — the default, credential-free adapter (W1).

A REAL, deterministic adapter (not a test mock): it records each call's kwargs in an
in-memory list and returns a ``WhatsAppReceipt`` with a synthetic ``fake-<uuid4>`` message
id. Selected by ``BE_WHATSAPP_SENDER_IMPL=fake`` (the default), so the backend runs the config
surface + the interim send with no provider account. W-live-test adds the free-form
``send_text``/``send_image_link`` (recorded like ``send_image``) for the interim path.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from backend.domain.models import WhatsAppReceipt


@dataclass(frozen=True, slots=True)
class SentImage:
    """One recorded ``send_image`` (template) call (test/introspection convenience)."""

    to: str
    image_url: str
    template_name: str
    sender_number: str
    caption: str | None


@dataclass(frozen=True, slots=True)
class SentText:
    """One recorded free-form ``send_text`` call (W-live-test interim send)."""

    to: str
    body: str
    sender_number: str


@dataclass(frozen=True, slots=True)
class SentImageLink:
    """One recorded free-form ``send_image_link`` call (W-live-test interim send)."""

    to: str
    image_url: str
    caption: str | None
    sender_number: str


class FakeWhatsAppSender:
    """Always-succeeds WhatsApp sender for credential-free local dev/tests."""

    def __init__(self) -> None:
        self.sent: list[SentImage] = []
        # W-live-test: the free-form interim calls are recorded on their own lists so tests can
        # assert the intro text + each photo were sent to the test number.
        self.sent_text: list[SentText] = []
        self.sent_image_links: list[SentImageLink] = []

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

    async def send_text(
        self, *, to: str, body: str, sender_number: str
    ) -> WhatsAppReceipt:
        self.sent_text.append(SentText(to=to, body=body, sender_number=sender_number))
        return WhatsAppReceipt(provider_message_id=f"fake-{uuid.uuid4()}", to=to)

    async def send_image_link(
        self,
        *,
        to: str,
        image_url: str,
        caption: str | None,
        sender_number: str,
    ) -> WhatsAppReceipt:
        self.sent_image_links.append(
            SentImageLink(
                to=to, image_url=image_url, caption=caption, sender_number=sender_number
            )
        )
        return WhatsAppReceipt(provider_message_id=f"fake-{uuid.uuid4()}", to=to)
