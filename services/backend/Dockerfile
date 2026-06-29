# Build context = repo root (uv workspace). See docker-compose.yml.
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# --- deps layer (cached unless manifests/lock change) ---
COPY pyproject.toml uv.lock ./
COPY services/backend/pyproject.toml services/backend/pyproject.toml
COPY services/ml_service/pyproject.toml services/ml_service/pyproject.toml
RUN uv sync --frozen --no-install-project --package backend --no-dev

# --- app layer ---
COPY services/backend services/backend
RUN uv sync --frozen --package backend --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
