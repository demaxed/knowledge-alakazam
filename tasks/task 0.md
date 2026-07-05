# Bootstrap Prompt for Codex

You are a senior Python backend engineer and software architect. You need to implement a production-oriented project from scratch for RAG-Anything / LightRAG + PostgreSQL/pgvector/Apache AGE + S3/MinIO + llm-wiki storage.

Work strictly task by task, using small atomic changes with clear, commit-sized diffs.

## Main Goal

In the current empty folder, initialize a Python project using `uv`, create agent instructions, and then implement the backend service through separate tasks:

* FastAPI service.
* `uv` as the Python package manager.
* RAG-Anything as the multimodal ingest pipeline.
* LightRAG as the RAG index/runtime.
* PostgreSQL as the production backend for LightRAG storages:

  * `PGKVStorage`
  * `PGVectorStorage`
  * `PGGraphStorage`
  * `PGDocStatusStorage`
* PostgreSQL must support `pgvector` and `Apache AGE`.
* MinIO/S3 for:

  * raw uploaded documents
  * parsed/extracted assets: images, table crops, equation crops, figures
* Store the llm-wiki not in Git, but in PostgreSQL as the canonical store:

  * pages
  * revisions
  * links/backlinks
  * claims
  * claim sources/provenance
  * compile jobs
  * validation results
* Git/Markdown can be supported only as an optional export target, but not as the source of truth.

## Important Rule for Codex Instructions

Create `AGENTS.md` as the main instruction file for Codex.

Also create `AGENT.md` as a compatibility alias/copy, because the project owner explicitly requested `AGENT.md`.

## Technology Stack

Use:

* Python 3.11+
* uv
* FastAPI
* Uvicorn
* Pydantic Settings
* SQLAlchemy 2.x async
* asyncpg
* Alembic
* boto3
* python-multipart
* pytest
* pytest-asyncio
* ruff
* mypy, if it does not create too much noise at the early stage
* RAG-Anything
* LightRAG HKU package

Do not use Poetry, Pipenv, or `requirements.txt` as the primary dependency management mechanism.

The primary source of dependencies must be `pyproject.toml` + `uv.lock`.

## Production Architecture

Implement a structure similar to this:

```text
.
├── AGENTS.md
├── AGENT.md
├── README.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── db.py
│   ├── s3_assets.py
│   ├── rag_runtime.py
│   ├── ingest_service.py
│   ├── schemas.py
│   └── api/
│       ├── __init__.py
│       ├── health.py
│       ├── ingest.py
│       ├── query.py
│       └── wiki.py
├── wiki/
│   ├── __init__.py
│   ├── models.py
│   ├── repository.py
│   ├── service.py
│   ├── compiler.py
│   └── validators.py
├── worker/
│   ├── __init__.py
│   └── ingest_worker.py
├── migrations/
│   ├── env.py
│   └── versions/
├── db/
│   └── init/
│       └── 001_extensions.sql
└── tests/
    ├── __init__.py
    ├── test_health.py
    ├── test_config.py
    ├── test_wiki_repository.py
    └── test_s3_assets.py
```

If during implementation it turns out that the RAG-Anything or LightRAG package has different current import paths or APIs, do not invent anything.

Inspect the installed package, README, package metadata, or source code inside `.venv`, then adapt the code and document the change in README.

## Core Assumptions

* A local production-like development environment is started through Docker Compose.
* The PostgreSQL service must use an image with `pgvector` and `Apache AGE`.
* If a suitable image is unavailable, propose a fallback in README, but the main compose setup should be runnable.
* MinIO is used as S3-compatible storage.
* The app container must include system dependencies for document parsing, including LibreOffice.
* RAG-Anything first writes parsed output locally, then our code uploads extracted assets to MinIO/S3.
* For LightRAG, all storage backend values must be configured through environment variables:

  * `LIGHTRAG_KV_STORAGE=PGKVStorage`
  * `LIGHTRAG_VECTOR_STORAGE=PGVectorStorage`
  * `LIGHTRAG_GRAPH_STORAGE=PGGraphStorage`
  * `LIGHTRAG_DOC_STATUS_STORAGE=PGDocStatusStorage`
* Embedding dimension must be configurable and treated as immutable for an already-created index.
* Implement multi-tenancy through `tenant_id`.
* Use `source_id` as a stable document ID.
* Do not implement full authentication in the first version, but leave architectural extension points for it.

## Implementation Style

* Write production-readable code, but avoid overengineering.
* Use async SQLAlchemy.
* All settings must go through `pydantic-settings`.
* Do not hardcode secrets.
* All public functions should have clear names.
* Ingest pipeline errors must be persisted in `ingest_job.error`.
* Add tests as you implement features.
* After each task, run:

  * `uv run ruff check .`
  * `uv run pytest`
* If mypy is enabled and the project is not ready for strict typing yet, configure a reasonable baseline.
* README must contain commands for running through `uv` and Docker Compose.

## First, Execute Task 0

Task 0: Bootstrap project.

Do the following:

1. Initialize the project with `uv`.
2. Create `pyproject.toml` with project metadata.
3. Add dependencies.
4. Create the basic folder structure.
5. Create `AGENTS.md` with working rules for Codex.
6. Create `AGENT.md` as a compatibility alias/copy.
7. Create `.env.example`.
8. Create a minimal `README.md`.
9. Add `ruff` configuration.
10. Add a minimal FastAPI app with `/health`.
11. Add `test_health.py`.
12. Run format/lint/tests.
13. At the end, provide a short report:

    * what files were created
    * what commands were run
    * what works
    * what next task is recommended

Do not implement everything at once.

After Task 0, stop and wait for the next command.