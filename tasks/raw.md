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
* PostgreSQL must support `
` and `Apache AGE`.
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

---

# Task 1: Docker Compose Production-Like Environment

Implement the Docker Compose environment for production-like local development.

Add:

1. `docker-compose.yml` with services:

   * `postgres`
   * `minio`
   * `create-buckets`
   * `app`

2. PostgreSQL:

   * use an image with `pgvector` and `Apache AGE`
   * database: `rag`
   * user: `rag`
   * password through env/example
   * healthcheck with `pg_isready`
   * persistent data volume
   * init SQL from `db/init/001_extensions.sql`

3. MinIO:

   * S3-compatible endpoint
   * console port
   * buckets:

     * `rag-raw`
     * `rag-assets`

4. App:

   * build from `Dockerfile`
   * depends on PostgreSQL healthcheck and bucket creation
   * expose port `8080:8080`
   * use `.env.example` as `env_file`
   * volumes:

     * `/data/rag_storage`
     * `/data/output`
     * `/data/inputs`

5. `Dockerfile`:

   * Python 3.11 slim
   * install `uv`
   * install system dependencies for document parsing:

     * libreoffice
     * poppler-utils
     * tesseract-ocr
     * curl
     * build-essential if needed
   * install app dependencies via `uv sync`
   * run `uvicorn app.main:app`

6. `db/init/001_extensions.sql`:

   * `CREATE EXTENSION IF NOT EXISTS vector;`
   * `CREATE EXTENSION IF NOT EXISTS age;`
   * safe `search_path` setup if required

7. Update README:

   * how to run `docker compose up --build`
   * how to open the MinIO console
   * how to check `/health`
   * which env variables are important

Acceptance criteria:

* `docker compose config` passes.
* `docker compose up --build` starts app, postgres, and minio.
* `/health` returns OK.
* README describes the startup flow.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 2: App Configuration and Database Layer

Implement the configuration and async database layer.

Add:

1. `app/config.py`

   * `Settings` based on `pydantic-settings`
   * env variables:

     * `ENV`
     * `SERVICE_NAME`
     * `APP_DATABASE_URL`
     * `RAG_WORKING_DIR`
     * `RAG_OUTPUT_DIR`
     * `RAG_INPUT_DIR`
     * `PARSER`
     * `PARSE_METHOD`
     * `OPENAI_API_KEY`
     * `OPENAI_BASE_URL`
     * `LLM_MODEL`
     * `VISION_MODEL`
     * `EMBEDDING_MODEL`
     * `EMBEDDING_DIM`
     * S3/MinIO settings
     * LightRAG storage settings

2. `app/db.py`

   * async engine
   * async sessionmaker
   * dependency `get_db_session`
   * lifespan init/dispose

3. Update `app/main.py`

   * FastAPI lifespan
   * include routers
   * health router

4. Tests:

   * config loads from environment
   * database URL parsing does not break
   * health endpoint still works

Acceptance criteria:

* Settings do not hardcode secrets.
* `.env.example` contains all variables.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 3: Alembic Migrations for llm-wiki Canonical Store

Implement the PostgreSQL schema for the llm-wiki canonical store.

Add Alembic and migrations for the following tables:

1. `wiki_page`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `slug TEXT NOT NULL`
   * `title TEXT NOT NULL`
   * `page_type TEXT NOT NULL DEFAULT 'concept'`
   * `status TEXT NOT NULL DEFAULT 'draft'`
   * `current_revision_id UUID NULL`
   * timestamps
   * unique `(tenant_id, slug)`

2. `wiki_revision`

   * `id UUID PK`
   * `page_id UUID FK`
   * `revision_no INT NOT NULL`
   * `content_format TEXT NOT NULL DEFAULT 'markdown'`
   * `content TEXT NOT NULL`
   * `content_json JSONB NULL`
   * `summary TEXT NULL`
   * `author_type TEXT NOT NULL DEFAULT 'agent'`
   * timestamp
   * unique `(page_id, revision_no)`

3. `wiki_link`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `from_page_id UUID FK`
   * `to_slug TEXT NOT NULL`
   * `link_type TEXT NOT NULL DEFAULT 'wikilink'`
   * timestamp
   * indexes for backlinks

4. `wiki_claim`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `page_id UUID FK`
   * `revision_id UUID FK`
   * `claim_text TEXT NOT NULL`
   * `support_status TEXT NOT NULL DEFAULT 'unknown'`
   * `confidence NUMERIC(5, 4) NULL`
   * timestamp

5. `wiki_claim_source`

   * `id UUID PK`
   * `claim_id UUID FK`
   * `source_id TEXT NOT NULL`
   * `document_uri TEXT NULL`
   * `chunk_id TEXT NULL`
   * `entity_id TEXT NULL`
   * `relation_id TEXT NULL`
   * `asset_url TEXT NULL`
   * `page_no INT NULL`
   * `bbox JSONB NULL`
   * `quote TEXT NULL`
   * `locator JSONB NOT NULL DEFAULT '{}'`
   * timestamp

6. `ingest_job`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `source_id TEXT NOT NULL`
   * raw bucket/key
   * enum-like status check:

     * pending
     * processing
     * succeeded
     * failed
   * error text
   * timestamps
   * unique `(tenant_id, source_id)`

7. `wiki_compile_job`

   * `id UUID PK`
   * `tenant_id`
   * `source_id`
   * `target_slug NULL`
   * status
   * error
   * timestamps

8. `wiki_validation_result`

   * `id UUID PK`
   * `tenant_id`
   * `page_id`
   * `revision_id`
   * `validator_name`
   * `severity`
   * `message`
   * `metadata JSONB`
   * timestamp

Also:

* Create SQLAlchemy models in `wiki/models.py`.
* Configure Alembic env for async SQLAlchemy metadata.
* Add README commands:

  * `uv run alembic upgrade head`
  * `uv run alembic revision --autogenerate -m "..."`
* Add model/repository tests where possible without a real PostgreSQL instance.
* If real PostgreSQL is required, mark the tests as integration tests.

Acceptance criteria:

* Alembic migration is generated and applicable.
* Models match the migration.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 4: WikiRepository and WikiService

Implement the repository/service layer for llm-wiki.

Add:

1. `wiki/repository.py`

   * `get_page_by_slug(tenant_id, slug)`
   * `create_page(...)`
   * `upsert_page_revision(...)`
   * `list_page_revisions(page_id)`
   * `get_current_revision(tenant_id, slug)`
   * `create_links_for_revision(...)`
   * `replace_links_for_page(...)`
   * `create_claim(...)`
   * `attach_claim_source(...)`
   * `list_backlinks(tenant_id, slug)`

2. `wiki/service.py`

   * higher-level methods:

     * `create_or_update_page`
     * `publish_page`
     * `get_page`
     * `add_claim_with_sources`
     * `rebuild_links_from_markdown`

3. Markdown wikilink parser:

   * find `[[Some Page]]`
   * slugify target
   * save links

4. API endpoints in `app/api/wiki.py`:

   * `POST /wiki/pages`
   * `GET /wiki/pages/{slug}`
   * `POST /wiki/pages/{slug}/revisions`
   * `GET /wiki/pages/{slug}/backlinks`

5. Pydantic schemas in `app/schemas.py`.

Acceptance criteria:

* Repository methods are async.
* Transactions are explicit and safe.
* Tests cover:

  * page creation
  * revision increment
  * wikilink extraction
  * backlinks
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 5: S3/MinIO Asset Store

Implement the S3-compatible asset layer.

Add `app/s3_assets.py`.

Requirements:

1. Class `S3AssetStore`.

2. Methods:

   * `ensure_buckets()`
   * `upload_raw_document(local_path, tenant_id, source_id) -> RawUploadResult`
   * `upload_output_tree(local_output_root, tenant_id, source_id) -> list[AssetUploadResult]`
   * `public_asset_url(bucket, key) -> str`
   * `download_raw_document(bucket, key, destination_path)`

3. Preserve relative paths:

   * local `/data/output/{tenant_id}/{source_id}/images/fig1.png`
   * object key `output/{tenant_id}/{source_id}/images/fig1.png`

4. Content-Type detection via `mimetypes`.

5. Error handling:

   * file not found
   * missing bucket
   * upload failed

6. Tests:

   * unit tests for key mapping
   * no real S3 required for unit tests
   * integration test may be skipped unless env is enabled

Acceptance criteria:

* No hardcoded bucket names.
* Public URL builds correctly.
* Key mapping is deterministic.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 6: LightRAG + RAG-Anything Runtime

Implement the runtime integration layer.

Add `app/rag_runtime.py`.

Requirements:

1. Create `RAGRuntime` class:

   * owns the LightRAG instance
   * owns the RAGAnything instance
   * supports async initialization
   * supports graceful shutdown if the package API supports it

2. LightRAG:

   * `working_dir` from settings
   * configurable LLM model function
   * configurable embedding function
   * storage backends through env
   * call `initialize_storages()`
   * call pipeline status initialization if required by the actual package API

3. RAG-Anything:

   * pass an existing LightRAG instance
   * configure vision model function
   * support image/table/equation processing flags if the actual package API supports them

4. LLM providers:

   * implement OpenAI-compatible default
   * use env:

     * `OPENAI_API_KEY`
     * `OPENAI_BASE_URL`
     * `LLM_MODEL`
     * `VISION_MODEL`
     * `EMBEDDING_MODEL`
     * `EMBEDDING_DIM`
   * keep the code isolated so another provider can be added later

5. Important:

   * do not invent imports
   * inspect the installed package API if needed
   * if the RAG-Anything/LightRAG API differs, adapt and document it in README

6. Add endpoint:

   * `POST /query`
   * body:

     * `tenant_id`
     * `question`
     * `mode`, default `hybrid`
     * `vlm_enhanced`, optional
   * returns answer and metadata

Acceptance criteria:

* App starts without initializing LLM if env says `RAG_RUNTIME_DISABLED=true` for tests/local.
* Runtime initialization is lazy or guarded for tests.
* Query endpoint returns a graceful error if runtime is disabled.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 7: Document Ingest Service

Implement the document ingest pipeline.

Add `app/ingest_service.py`.

Flow:

1. Accept local file path, `tenant_id`, optional `source_id`.
2. Normalize/copy input to:

   * `/data/inputs/{tenant_id}/{source_id}/{filename}`
3. Upload raw document to S3/MinIO:

   * bucket `rag-raw`
   * key `{tenant_id}/{source_id}/{filename}`
4. Call RAG-Anything:

   * `process_document_complete`
   * output dir:

     * `/data/output/{tenant_id}/{source_id}`
   * parser from settings
   * parse method from settings
5. Upload extracted output tree to S3/MinIO:

   * bucket `rag-assets`
   * key prefix `output/{tenant_id}/{source_id}/...`
6. Save/update `ingest_job` status:

   * pending
   * processing
   * succeeded
   * failed
7. Return:

   * tenant_id
   * source_id
   * raw_uri
   * output_dir
   * asset_count
   * asset URLs

API endpoint:

* `POST /ingest`

  * multipart file
  * `tenant_id`
  * optional `source_id`
  * for now can run synchronously if `INGEST_SYNC=true`
  * otherwise creates a pending `ingest_job`

Acceptance criteria:

* Synchronous ingest path works structurally.
* Runtime disabled mode returns explicit 503 or a clear error.
* Ingest job records error on failure.
* Tests cover path normalization and job status transitions.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 8: Ingest Worker

Implement a worker for async ingest jobs.

Add `worker/ingest_worker.py`.

Requirements:

1. Worker loop:

   * claim next pending job with `FOR UPDATE SKIP LOCKED`
   * mark processing
   * download raw file from S3/MinIO
   * run ingest service
   * mark succeeded or failed

2. CLI entrypoint:

   * `uv run python -m worker.ingest_worker`

3. Config:

   * poll interval
   * max attempts if implemented
   * graceful shutdown on SIGINT/SIGTERM

4. Docker Compose:

   * optional `worker` service
   * can be enabled through profile `worker`

Acceptance criteria:

* No double-claim when multiple workers run.
* Errors are persisted to DB.
* README has the worker command.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 9: llm-wiki Compiler Skeleton

Implement a `WikiCompiler` skeleton that builds wiki pages on top of RAG evidence.

Add `wiki/compiler.py`.

Scope of the first version:

1. `WikiCompiler` class:

   * `compile_source_to_pages(tenant_id, source_id)`
   * `compile_topic_page(tenant_id, topic, evidence_query)`
   * `update_existing_page_with_evidence(tenant_id, slug, evidence)`

2. It must use the RAG runtime to search evidence:

   * query LightRAG/RAG-Anything
   * default mode: `hybrid`

3. It must create/update wiki pages through `WikiService`.

4. Page format:

   * Markdown
   * sections:

     * Summary
     * Key Concepts
     * Source-backed Claims
     * Related Pages
     * Open Questions
   * wikilinks through `[[...]]`

5. Provenance:

   * claims should be saved to `wiki_claim`
   * sources should be saved to `wiki_claim_source`
   * if exact chunk/entity IDs are unavailable from the current RAG API, save the best available locator metadata and document/source ID

6. Add compile job table usage:

   * create pending job
   * mark processing/succeeded/failed

7. API endpoint:

   * `POST /wiki/compile`
   * params:

     * `tenant_id`
     * `source_id`, optional
     * `topic`, optional
     * `target_slug`, optional

Acceptance criteria:

* Compiler is deterministic where possible.
* No fake citations.
* If evidence lacks structured source IDs, preserve raw metadata and document the limitation in README.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 10: Validation and Observability

Add a validation layer and basic observability.

Validation:

1. `wiki/validators.py`

   * broken wikilinks validator
   * unsupported claims validator skeleton
   * stale page validator skeleton
   * duplicate slug/title validator

2. Save results to `wiki_validation_result`.

3. API:

   * `POST /wiki/pages/{slug}/validate`
   * `GET /wiki/pages/{slug}/validation-results`

Observability:

1. Structured logging.
2. Request ID middleware.
3. Log ingest job lifecycle.
4. Log RAG runtime initialization.
5. Log S3 upload counts.
6. Health endpoint should include:

   * app status
   * DB reachable
   * optional S3 reachable
   * RAG runtime enabled/disabled

Acceptance criteria:

* Validation endpoints work.
* Health endpoint is useful for operations.
* Logs do not leak secrets.
* `uv run ruff check .` passes.
* `uv run pytest` passes.

---

# Task 11: Final Hardening and Docs

Perform the final production-hardening pass.

Requirements:

1. README:

   * architecture overview
   * local run with uv
   * local run with Docker Compose
   * migrations
   * ingest example with curl
   * query example with curl
   * wiki page example
   * worker usage
   * env variables table
   * known limitations

2. Add `docs/architecture.md`:

   * components
   * data flow
   * storage model
   * ingest lifecycle
   * wiki compiler lifecycle
   * S3 asset strategy
   * PostgreSQL schema explanation

3. Add `docs/operations.md`:

   * backup considerations
   * embedding dimension immutability
   * PostgreSQL extensions
   * object storage lifecycle
   * how to reindex
   * how to replay wiki compile jobs

4. Add Makefile or task commands if useful:

   * `make test`
   * `make lint`
   * `make format`
   * `make migrate`
   * but keep uv as the primary tool

5. Run:

   * `uv run ruff format .`
   * `uv run ruff check .`
   * `uv run pytest`

6. Fix all issues.

Acceptance criteria:

* Project is understandable from README.
* Docker Compose can start the local stack.
* Tests pass.
* No secrets are committed.
* Known limitations are explicit.
