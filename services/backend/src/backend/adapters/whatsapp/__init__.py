"""WhatsApp sender adapters (W1).

One module per outbound WhatsApp provider, selected by ``BE_WHATSAPP_SENDER_IMPL``. ``fake`` is
the default, credential-free adapter (real + deterministic, not a mock); ``gupshup`` is the
Gupshup BSP; ``meta`` is the direct Meta WhatsApp Cloud API. Each real provider's one platform
secret is a settings env var — never a per-school column.
"""
