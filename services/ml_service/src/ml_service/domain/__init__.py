"""Pure domain layer — imports NO third-party ML/IO libraries.

Will hold: models (FaceBox, Embedding, Candidate, Thresholds, MatchRecord,
InferenceJob, Frame), the 8 Protocol ports (requirements §9), the pure
``apply_threshold_and_gap`` decision function (requirements §6.2), and errors.

Constants to lock here when models land:
    EMBEDDING_DIM = 512          # ArcFace R100
    SIMILARITY_METRIC = "cosine" # L2-normalized -> inner product
"""
