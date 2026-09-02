"""HTTP ``WhatsAppSender`` over Gupshup (W1; wired into the send path in W2).

The real provider adapter, selected by ``BE_WHATSAPP_SENDER_IMPL=gupshup``. Mirrors
``ml_client/http_enrollment.py``'s httpx pattern: a fresh ``httpx.AsyncClient`` per call,
``raise_for_status()``, and ``httpx.HTTPError`` wrapped in ``UpstreamError`` (→502).

The endpoint / ``apikey`` auth / form fields / template+image payload / response shape below were
CONFIRMED against Gupshup's current public docs (docs.gupshup.io/docs/template-messages +
/reference/msg) — the **self-serve** WhatsApp API (``apikey`` header), NOT the Partner API
(``partner.gupshup.io`` + a ``token`` header). The one value that MUST be a Gupshup template
**UUID** (not a display name) is ``template_name`` — the school's configured "Template ID".
Still untested end-to-end until a live account exists — the live smoke verifies real delivery +
that the approved template's UUID/params line up. The ``api_key`` is NEVER logged.
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
        # Self-serve template-message endpoint (docs-confirmed). Media (image) templates use the
        # SAME endpoint as text templates; the image differs only by the added `message` field.
        url = f"{self._base_url}/wa/api/v1/template/msg"
        # Auth: the account API key in a lowercase `apikey` header (docs-confirmed, not Bearer).
        # Never logged.
        headers = {
            "apikey": self._api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        # `template.id` MUST be the approved template's UUID (the school's configured "Template
        # ID"), NOT its display name (docs example: {"id":"c6aecef6-...","params":[...]}).
        # `params` are the ordered body-variable values — [] for a static-body template (the
        # recommended one); a caption is threaded here ONLY if the template has a {{1}} variable.
        template: dict[str, Any] = {"id": template_name, "params": []}
        if caption is not None:
            template["params"] = [caption]
        # The image header carries the photo as a fetch-at-send-time `link` (docs-confirmed;
        # present only for a Media-Image template).
        message = {
            "type": "image",
            "image": {"link": image_url},
        }
        # Fields match Gupshup's confirmed /template/msg curl exactly. (That curl omits `channel`;
        # if a send is ever rejected for a missing channel, add `"channel": "whatsapp"`.)
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
        # Defense-in-depth: Gupshup normally returns a non-2xx on failure (caught above), but a
        # 2xx body with an explicit error status is treated as a failure too (PII-free message).
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise UpstreamError(f"WhatsApp send rejected for {_redact(to)}")
        return _to_receipt(payload, to=to)

    async def send_text(
        self, *, to: str, body: str, sender_number: str
    ) -> WhatsAppReceipt:
        # FREE-FORM text via the session-message endpoint /wa/api/v1/msg (NOT /template/msg) —
        # deliverable only inside an open 24h session window (interim testing). CONFIRM against
        # Gupshup docs (docs.gupshup.io/reference/msg).
        message = {"type": "text", "text": body}
        return await self._send_freeform(to=to, message=message, sender_number=sender_number)

    async def send_image_link(
        self,
        *,
        to: str,
        image_url: str,
        caption: str | None,
        sender_number: str,
    ) -> WhatsAppReceipt:
        # FREE-FORM image via /wa/api/v1/msg. The image is a fetch-at-send-time URL
        # (originalUrl/previewUrl); `caption` is omitted when None. CONFIRM against Gupshup docs.
        message: dict[str, Any] = {
            "type": "image",
            "originalUrl": image_url,
            "previewUrl": image_url,
        }
        if caption is not None:
            message["caption"] = caption
        return await self._send_freeform(to=to, message=message, sender_number=sender_number)

    async def _send_freeform(
        self, *, to: str, message: dict[str, Any], sender_number: str
    ) -> WhatsAppReceipt:
        """POST a free-form (session) message to /wa/api/v1/msg. Shares the apikey auth + the
        redacted-error + the receipt parse with the template path."""
        url = f"{self._base_url}/wa/api/v1/msg"
        headers = {
            "apikey": self._api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }
        form = {
            "channel": "whatsapp",
            "source": sender_number,
            "destination": to,
            "src.name": self._app_name,
            "message": json.dumps(message),
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(url, headers=headers, data=form)
                resp.raise_for_status()
                payload: Any = resp.json()
        except httpx.HTTPError as exc:
            raise UpstreamError(
                f"WhatsApp send failed for {_redact(to)}: {exc}"
            ) from exc
        if isinstance(payload, dict) and payload.get("status") == "error":
            raise UpstreamError(f"WhatsApp send rejected for {_redact(to)}")
        return _to_receipt(payload, to=to)


def _redact(number: str) -> str:
    """Mask a recipient number for logging — keep only the last 4 digits (PII-free)."""
    if len(number) <= 4:
        return "*" * len(number)
    return "*" * (len(number) - 4) + number[-4:]


def _to_receipt(payload: Any, *, to: str) -> WhatsAppReceipt:
    # Docs-confirmed success body: {"status":"submitted","messageId":"<uuid>"}. `messageId` is
    # Gupshup's only id field (camelCase); a non-dict / missing id → "" (a non-2xx already raised).
    message_id = ""
    if isinstance(payload, dict):
        message_id = str(payload.get("messageId") or "")
    return WhatsAppReceipt(provider_message_id=message_id, to=to)
