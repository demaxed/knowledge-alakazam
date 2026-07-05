# Agent Instructions

This repository is implemented task by task. Keep changes small, atomic, and suitable for a single commit.

## Project Direction

- Build a production-oriented Python 3.11+ backend for RAG-Anything, LightRAG, PostgreSQL with pgvector and Apache AGE, S3-compatible asset storage, and PostgreSQL-backed llm-wiki storage.
- Use FastAPI for the HTTP API.
- Use `uv` as the only primary Python package manager.
- Keep dependencies in `pyproject.toml` and `uv.lock`.
- Do not add Poetry, Pipenv, or `requirements.txt` as primary dependency management.
- Implement multi-tenancy with `tenant_id`.
- Use `source_id` as the stable document identifier.
- Store llm-wiki state in PostgreSQL as the source of truth. Git/Markdown may only be an export target.

## Engineering Rules

- Prefer production-readable code over clever abstractions.
- Use async SQLAlchemy for database access.
- Route all configuration through `pydantic-settings`.
- Do not hardcode secrets.
- Persist ingest pipeline failures to `ingest_job.error` when that model is introduced.
- Inspect installed RAG-Anything and LightRAG package APIs before wiring runtime imports.
- Document any discovered package/API mismatch in `README.md`.

## Verification

After each implementation task, run:

```bash
uv run ruff check .
uv run pytest
```

If formatting is needed, run:

```bash
uv run ruff format .
```

`AGENT.md` is a compatibility copy requested by the project owner. Keep it synchronized with this file.
