"""HTTP ``WhatsAppSender`` over the Meta WhatsApp Cloud API (alt provider).

The real provider adapter, selected by ``BE_WHATSAPP_SENDER_IMPL=meta``. Sends directly through
the platform's own Meta WhatsApp Business account (the Graph API), rather than a BSP like Gupshup.
Mirrors the Gupshup adapter's httpx pattern: a fresh ``httpx.AsyncClient`` per call,
``raise_for_status()``, and ``httpx.HTTPError`` wrapped in ``UpstreamError`` (→502).

The endpoint / Bearer auth / template+image payload / response shape below follow Meta's Cloud
API docs (a template message with an image-header component). Still untested end-to-end until a
live Meta account exists — the live smoke verifies real delivery + that the approved template's
name/language line up; version-sensitive lines are flagged CONFIRM against Meta Cloud API docs.

W-live-test: BOTH the access token AND the sender ``phone_number_id`` are resolved FRESH per send
via injected providers (DB-stored value first, env fallback — see the container), so a UI edit to
either takes effect immediately without a rebuild. The token is NEVER logged.

Two quirks vs Gupshup:
- The per-call ``sender_number`` kwarg is IGNORED — Meta's sender is the ``phone_number_id`` in the
  URL, not a body field. That ID is DB-configurable (the platform ``sender_number``, resolved by
  ``phone_number_id_provider``) with an env fallback; the per-call ``sender_number`` (a Gupshup-era
  per-school concept) still has no effect here.
- Meta identifies a template by its NAME (+ a required language code), not a UUID.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from backend.domain.errors import UpstreamError
from backend.domain.models import WhatsAppReceipt


class MetaWhatsAppSender:
    """``WhatsAppSender`` over the Meta WhatsApp Cloud API (Graph API) at ``base_url``.

    The platform owns ONE Meta WhatsApp Business account → one access token + one sender
    ``phone_number_id``, BOTH resolved fresh per send by their providers (``token_provider`` /
    ``phone_number_id_provider``; DB-stored first, env fallback). ``to`` (the recipient) is
    per-call; the per-call ``sender_number`` kwarg is ignored (Meta's sender is the resolved
    ``phone_number_id`` in the URL — see the module docstring).
    """

    def __init__(
        self,
        *,
        token_provider: Callable[[], Awaitable[str]],
        phone_number_id_provider: Callable[[], Awaitable[str]],
        api_version: str,
        base_url: str,
        template_lang: str,
        timeout_s: float = 30.0,
    ) -> None:
        self._token_provider = token_provider
        self._phone_number_id_provider = phone_number_id_provider
        self._api_version = api_version
        self._base_url = base_url.rstrip("/")
        self._template_lang = template_lang
        self._timeout = timeout_s

    def _messages_url(self, phone_number_id: str) -> str:
        # Cloud API messages endpoint; the sender is the phone_number_id in the path.
        return f"{self._base_url}/{self._api_version}/{phone_number_id}/messages"

    async def _post(self, body: dict[str, Any], *, to: str) -> WhatsAppReceipt:
        """POST a message body to the Cloud API. Auth: a Bearer access token resolved fresh per
        send (never logged). The sender phone-number ID is likewise resolved fresh per send
        (W-live-test — DB-configurable). Returns a receipt or raises ``UpstreamError`` with the
        recipient REDACTED."""
        token = await self._token_provider()
        phone_number_id = await self._phone_number_id_provider()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    self._messages_url(phone_number_id), headers=headers, json=body
                )
                resp.raise_for_status()
                payload: Any = resp.json()
        except httpx.HTTPError as exc:
            # REDACT the recipient (all but the last 4 digits) — it never lands in a log/error
            # string. The access token is likewise never included.
            raise UpstreamError(
                f"WhatsApp send failed for {_redact(to)}: {exc}"
            ) from exc
        # Defense-in-depth: Meta normally returns a non-2xx on failure (caught above), but a 2xx
        # body carrying an `error` object is treated as a failure too (PII-free message).
        if isinstance(payload, dict) and payload.get("error"):
            raise UpstreamError(f"WhatsApp send rejected for {_redact(to)}")
        return _meta_to_receipt(payload, to=to)

    async def send_image(
        self,
        *,
        to: str,
        image_url: str,
        template_name: str,
        sender_number: str,
        caption: str | None = None,
    ) -> WhatsAppReceipt:
        # A template message with an image-header component. Meta matches the template by NAME +
        # language code (CONFIRM against Meta Cloud API docs at integration time). The image is a
        # fetch-at-send-time `link`. A body component is added ONLY when a caption is provided
        # (the recommended template is static → header only; the share service passes caption=None).
        # (sender_number is intentionally ignored — see the module docstring.)
        components: list[dict[str, Any]] = [
            {
                "type": "header",
                "parameters": [{"type": "image", "image": {"link": image_url}}],
            }
        ]
        if caption is not None:
            components.append(
                {"type": "body", "parameters": [{"type": "text", "text": caption}]}
            )
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": self._template_lang},
                "components": components,
            },
        }
        return await self._post(body, to=to)

    async def send_text(
        self, *, to: str, body: str, sender_number: str
    ) -> WhatsAppReceipt:
        # FREE-FORM text message (no template) — only deliverable inside an open 24-hour customer
        # window (interim testing to a number that messaged the business first). CONFIRM against
        # Meta Cloud API docs. (sender_number is ignored — the sender is the phone_number_id.)
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": body},
        }
        return await self._post(payload, to=to)

    async def send_image_link(
        self,
        *,
        to: str,
        image_url: str,
        caption: str | None,
        sender_number: str,
    ) -> WhatsAppReceipt:
        # FREE-FORM image message (no template) — like send_text, only inside an open 24h window.
        # The image is a fetch-at-send-time `link`; `caption` is omitted when None. CONFIRM
        # against Meta Cloud API docs. (sender_number is ignored — see the module docstring.)
        image: dict[str, Any] = {"link": image_url}
        if caption is not None:
            image["caption"] = caption
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "image",
            "image": image,
        }
        return await self._post(payload, to=to)


def _redact(number: str) -> str:
    """Mask a recipient number for logging — keep only the last 4 digits (PII-free)."""
    if len(number) <= 4:
        return "*" * len(number)
    return "*" * (len(number) - 4) + number[-4:]


def _meta_to_receipt(payload: Any, *, to: str) -> WhatsAppReceipt:
    # Cloud API success body: {"messaging_product":"whatsapp","contacts":[…],
    # "messages":[{"id":"wamid…"}]}. A non-dict / missing messages id → "" (a non-2xx already
    # raised above).
    message_id = ""
    if isinstance(payload, dict):
        messages = payload.get("messages")
        if isinstance(messages, list) and messages and isinstance(messages[0], dict):
            message_id = str(messages[0].get("id") or "")
    return WhatsAppReceipt(provider_message_id=message_id, to=to)
