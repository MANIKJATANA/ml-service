"""HTTP ``WhatsAppSender`` over Gupshup (W1).

The real provider adapter, selected by ``BE_WHATSAPP_SENDER_IMPL=gupshup``. Mirrors
``ml_client/http_enrollment.py``'s httpx pattern: a fresh ``httpx.AsyncClient`` per call,
``raise_for_status()``, and ``httpx.HTTPError`` wrapped in ``UpstreamError`` (→502).

IMPORTANT: the exact Gupshup endpoint / headers / template-message payload are PROVIDER-DOC-
DEPENDENT and UNTESTABLE until a live Gupshup account exists. Every such line below is a
best-effort template-message POST written from the public Gupshup shape and is flagged
"CONFIRM against Gupshup live docs at integration time." — do not treat it as verified. The
``api_key`` is NEVER logged.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from backend.domain.errors import UpstreamError
from backend.domain.models import WhatsAppReceipt


class GupshupWhatsAppSender:
    """``WhatsAppSender`` over the Gupshup WhatsApp API against ``base_url``.

    The platform owns ONE Gupshup account → one ``api_key`` + one registered ``app_name``
    (source app name). ``sender_number`` (the school's approved sender) and ``to`` (the
    recipient) are per-call.
    """

    def __init__(
        self, *, api_key: str, base_url: str, app_name: str, timeout_s: float = 30.0
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._app_name = app_name
        self._timeout = timeout_s

    async def send_image(
        self,
        *,
        to: str,
        image_url: str,
        template_name: str,
        sender_number: str,
        caption: str | None = None,
    ) -> WhatsAppReceipt:
        # CONFIRM against Gupshup live docs at integration time: the template-message endpoint.
        url = f"{self._base_url}/wa/api/v1/template/msg"
        # CONFIRM against Gupshup live docs at integration time: the auth header carries the
        # api key. Never logged.
        headers = {
            "apikey": self._api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # CONFIRM against Gupshup live docs at integration time: the template payload shape.
        # A template message with an image header component; the caption (if any) is a body
        # parameter. Gupshup expects JSON-encoded fields inside a form body.
        template: dict[str, Any] = {"id": template_name, "params": []}
        if caption is not None:
            template["params"] = [caption]
        message = {
            "type": "image",
            "image": {"link": image_url},
        }
        form = {
            "source": sender_number,
            "destination": to,
            "src.name": self._app_name,
            "template": json.dumps(template),
            "message": json.dumps(message),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, data=form)
                resp.raise_for_status()
                payload: Any = resp.json()
        except httpx.HTTPError as exc:
            # W2 lit up the send path: REDACT the recipient number (all but the last 4 digits)
            # so it never lands in a log/error string. The api_key is likewise never included.
            raise UpstreamError(
                f"WhatsApp send failed for {_redact(to)}: {exc}"
            ) from exc
        return _to_receipt(payload, to=to)


def _redact(number: str) -> str:
    """Mask a recipient number for logging — keep only the last 4 digits (PII-free)."""
    if len(number) <= 4:
        return "*" * len(number)
    return "*" * (len(number) - 4) + number[-4:]


def _to_receipt(payload: Any, *, to: str) -> WhatsAppReceipt:
    # CONFIRM against Gupshup live docs at integration time: the success body carries a
    # message id (commonly ``messageId``). Fall back to empty if the shape differs; a non-2xx
    # would already have raised above.
    message_id = ""
    if isinstance(payload, dict):
        raw = payload.get("messageId") or payload.get("message_id") or ""
        message_id = str(raw)
    return WhatsAppReceipt(provider_message_id=message_id, to=to)
