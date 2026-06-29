"""Adapters — the ONLY place concrete libraries (faiss, insightface, redis,
sqlalchemy, azure-storage-blob, decord) may be imported.

One subpackage per port: detectors/, embedders/, vector_index/, media_store/,
video/, repository/, queue/. See architecture §5–§6.
"""
