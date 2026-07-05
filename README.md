# Knowledge Alakazam

Production-oriented backend for RAG-Anything and LightRAG with PostgreSQL-backed storage, S3-compatible document assets, and PostgreSQL-backed llm-wiki state.

Task 0 bootstraps the project only: FastAPI, configuration, dependency management, and a health endpoint. RAG runtime, ingest, PostgreSQL models, S3 asset handling, Docker Compose, and migrations are intentionally left for later tasks.

## Requirements

- Python 3.11 through 3.13
- `uv`

The Python upper bound is intentional for the initial lockfile because the current RAG and ML dependency stack is resolved for the actively supported 3.11-3.13 range.

## Local Development

Install the base service dependencies:

```bash
uv sync
```

Install optional RAG dependencies when working on ingest or runtime integration:

```bash
uv sync --extra rag
```

Run the API locally:

```bash
uv run uvicorn app.main:app --reload
```

Check the health endpoint:

```bash
curl http://127.0.0.1:8000/health
```

Run checks:

```bash
uv run ruff check .
uv run pytest
```

## Docker Compose

Docker Compose is scheduled for Task 1. Once `docker-compose.yml` exists, the intended local production-like startup command is:

```bash
docker compose up --build
```

## Configuration

Copy `.env.example` to `.env` for local overrides. Do not commit secrets.
