# ML service image. Build context = repo root (uv workspace). See docker-compose.yml.
#
# ONE image, THREE roles (the command selects which):
#   API     : uvicorn ml_service.api.main:app  (default CMD)
#   worker  : python -m ml_service.workers.inference_worker
#   migrate : alembic -c services/ml_service/alembic.ini upgrade head
#
# CPU by default (onnxruntime + faiss-cpu). GPU is a documented swap: base off a
# CUDA image and replace onnxruntime with onnxruntime-gpu (see docs/08-deployment.md).
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# Runtime shared libs the wheels dlopen on slim:
#   libgomp1          — OpenMP, required by faiss-cpu and onnxruntime
#   libgl1, libglib2.0-0 — required by opencv (insightface pulls full opencv-python)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# --- bake the InsightFace buffalo_l bundle at build time (no cold-start
# download; models present in the image). We fetch the official release zip with
# the stdlib (version-independent of the insightface download API) and extract
# the .onnx files directly under /models/buffalo_l. Adapters read ML_MODEL_DIR.
RUN python -c "import io,os,urllib.request,zipfile; d='/models/buffalo_l'; os.makedirs(d,exist_ok=True); z=zipfile.ZipFile(io.BytesIO(urllib.request.urlopen('https://github.com/deepinsight/insightface/releases/download/v0.7/buffalo_l.zip',timeout=180).read())); z.extractall(d); print(sorted(os.listdir(d)))"
ENV ML_MODEL_DIR=/models/buffalo_l

# --- deps layer (cached unless manifests/lock change) ---
COPY pyproject.toml uv.lock ./
COPY services/ml_service/pyproject.toml services/ml_service/pyproject.toml
COPY services/backend/pyproject.toml services/backend/pyproject.toml
RUN uv sync --frozen --no-install-project --package ml-service --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# --- app layer ---
COPY services/ml_service services/ml_service
RUN uv sync --frozen --package ml-service --no-dev

EXPOSE 8000
CMD ["uvicorn", "ml_service.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
