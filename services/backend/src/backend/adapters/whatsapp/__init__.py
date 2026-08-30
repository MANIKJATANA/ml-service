"""WhatsApp sender adapters (W1).

One subpackage per outbound WhatsApp provider. ``fake`` is the default, credential-free
adapter (real + deterministic, not a mock); ``gupshup`` is the real provider behind a config
flag. The one platform provider secret is a settings env var — never a per-school column.
"""
