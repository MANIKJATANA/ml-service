"""Backend / core system API.

Owns uploads, storage, notifications, consent, and distribution UX. Calls the
ML service's enrollment API and enqueues inference jobs. The ML service never
calls back into the backend.
"""

__version__ = "0.1.0"
