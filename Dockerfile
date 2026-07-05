FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    libreoffice \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

COPY pyproject.toml uv.lock ./

ARG INSTALL_RAG_EXTRAS=false
RUN if [ "$INSTALL_RAG_EXTRAS" = "true" ]; then \
    uv sync --frozen --no-dev --no-install-project --extra rag; \
    else \
    uv sync --frozen --no-dev --no-install-project; \
    fi

COPY app ./app
COPY wiki ./wiki
COPY worker ./worker

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/rag_storage /data/output /data/inputs \
    && chown -R appuser:appuser /app /data

USER appuser

EXPOSE 8080

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
