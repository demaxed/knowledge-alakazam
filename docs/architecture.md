# Architecture

Knowledge Alakazam is a FastAPI service for multimodal document ingest, RAG
querying, and PostgreSQL-backed llm-wiki generation. The project is structured
so local development resembles production infrastructure while keeping optional
RAG dependencies disabled by default for fast tests and local startup.

## Components

### API Service

The FastAPI application is created in `app/main.py`. It wires:

- settings from `app/config.py`
- async SQLAlchemy engine/session lifecycle from `app/db.py`
- structured logging and request IDs from `app/observability.py`
- route modules in `app/api/`
- tenant-scoped RAG runtime registry from `app/rag_runtime.py`

The API exposes:

- `GET /health`
- `POST /ingest`
- `POST /query`
- `POST /wiki/pages`
- `GET /wiki/pages/{slug}`
- `POST /wiki/pages/{slug}/revisions`
- `GET /wiki/pages/{slug}/backlinks`
- `POST /wiki/compile`
- `POST /wiki/pages/{slug}/validate`
- `GET /wiki/pages/{slug}/validation-results`

### PostgreSQL

PostgreSQL is the primary state store. It owns:

- app job state
- llm-wiki canonical pages and revisions
- wiki links and backlinks
- claim and provenance records
- compile job state
- validation results
- LightRAG storage backends through `PGKVStorage`, `PGVectorStorage`,
  `PGGraphStorage`, and `PGDocStatusStorage`

The local database image is built from an Apache AGE PostgreSQL 16 base image
and compiles pgvector into the same image. `db/init/001_extensions.sql` creates
the `vector` and `age` extensions when the database volume is initialized.

### S3-Compatible Object Storage

`app/s3_assets.py` provides `S3AssetStore`, a small boto3-based adapter around
MinIO or another S3-compatible service. It is responsible for:

- ensuring buckets exist
- uploading raw documents
- uploading parsed output trees
- deterministic key mapping
- public asset URL construction
- raw document download for workers

Bucket names are settings-driven. The default local buckets are `rag-raw` and
`rag-assets`.

### RAG Runtime

`app/rag_runtime.py` isolates LightRAG and RAG-Anything imports and provider
configuration. Runtime instances are lazy, tenant-scoped, and cached per
process.

The runtime:

- maps `tenant_id` to a safe LightRAG workspace name
- creates a LightRAG instance using configured PostgreSQL storage selectors
- calls LightRAG storage initialization
- creates RAG-Anything with the existing LightRAG instance
- exposes async query and document processing methods
- finalizes storages during app shutdown when the package API supports it

OpenAI-compatible LLM, vision, and embedding functions are the default provider
implementation. Provider details are kept isolated so a different provider can
be added without changing route or service code.

### Ingest Service

`app/ingest_service.py` coordinates document ingest. It depends on:

- `Settings`
- `RAGRuntimeRegistry`
- `S3AssetStore`
- `IngestJobRepository`

The API can run ingest synchronously or create a pending job for the worker,
controlled by `INGEST_SYNC`.

### Ingest Worker

`worker/ingest_worker.py` implements the async ingest worker. It claims pending
jobs and stale `processing` jobs with expired leases using
`FOR UPDATE SKIP LOCKED`, which allows multiple workers to run without
double-claiming the same active lease. Claimed jobs store attempt count,
claim/heartbeat timestamps, and a worker lock owner.

### llm-wiki

The `wiki/` package contains:

- `models.py`: SQLAlchemy models
- `repository.py`: explicit async persistence methods
- `service.py`: page and link workflows
- `compiler.py`: deterministic compiler skeleton over RAG evidence
- `validators.py`: validation service and validator implementations

The llm-wiki source of truth is PostgreSQL. Markdown content is stored in
`wiki_revision.content`; Git or Markdown file export can be added as a
secondary export target later.

## Data Flow

### Query Flow

1. Client sends `POST /query` with `tenant_id`, `question`, and `mode`.
2. The route asks `RAGRuntimeRegistry` for the tenant runtime.
3. If disabled, the route returns HTTP 503 with a clear message.
4. If enabled, the runtime initializes lazily if needed.
5. Runtime delegates to RAG-Anything or LightRAG query APIs.
6. The API returns `answer` and runtime metadata.

### Wiki Page Flow

1. Client creates a page with `POST /wiki/pages`.
2. `WikiService` normalizes or accepts the slug.
3. `WikiRepository` creates or updates `wiki_page`.
4. A new `wiki_revision` is inserted.
5. Markdown wikilinks such as `[[Some Topic]]` are extracted and stored in
   `wiki_link`.
6. The page's `current_revision_id` is updated.

### Validation Flow

1. Client calls `POST /wiki/pages/{slug}/validate`.
2. `WikiValidationService` loads the current page and revision.
3. Validators inspect wikilinks, claims, freshness, and duplicate titles.
4. Existing validation rows for that page/revision are replaced.
5. Results are returned and can later be read with
   `GET /wiki/pages/{slug}/validation-results`.

## Storage Model

### PostgreSQL

PostgreSQL stores durable relational state and LightRAG production data. The app
schema uses UUID primary keys, `tenant_id` for logical tenancy, and timestamp
columns for lifecycle tracking.

LightRAG uses PostgreSQL through package storage backends configured by
environment variables:

- `LIGHTRAG_KV_STORAGE=PGKVStorage`
- `LIGHTRAG_VECTOR_STORAGE=PGVectorStorage`
- `LIGHTRAG_GRAPH_STORAGE=PGGraphStorage`
- `LIGHTRAG_DOC_STATUS_STORAGE=PGDocStatusStorage`

### Object Storage

Raw uploaded documents and parsed assets are stored outside Git:

- Raw bucket key: `{tenant_id}/{source_id}/{filename}`
- Asset bucket key: `output/{tenant_id}/{source_id}/{relative_path}`

This separates immutable source material from derived assets while keeping key
mapping deterministic and traceable.

### Local Runtime Files

The service still uses local runtime directories because RAG-Anything writes
parsed output locally before upload:

- `RAG_INPUT_DIR`: normalized input copies
- `RAG_OUTPUT_DIR`: parser output before S3 upload
- `RAG_WORKING_DIR`: LightRAG working directory

In Docker Compose these are persistent named volumes under `/data`.

## Ingest Lifecycle

Synchronous ingest:

1. Receive multipart upload.
2. Normalize `tenant_id` and `source_id`.
3. Copy the file to `RAG_INPUT_DIR/{tenant_id}/{source_id}/{filename}`.
4. Upload raw file to `S3_BUCKET_RAW`.
5. Upsert `ingest_job` and mark it `processing`.
6. Run `RAGAnything.process_document_complete(...)`.
7. Upload parsed output tree to `S3_BUCKET_ASSETS`.
8. Mark job `succeeded`.
9. On failure, mark job `failed` and persist `ingest_job.error`.

Asynchronous ingest:

1. API stages and uploads the raw document.
2. API creates or updates a `pending` `ingest_job`.
3. Worker claims one pending or stale expired-lease job with
   `FOR UPDATE SKIP LOCKED`.
4. Worker downloads the raw object to local input storage.
5. Worker heartbeats the lease while running the same processing path.
6. Worker persists `succeeded` or `failed`; stale jobs that exceed
   `WORKER_JOB_MAX_ATTEMPTS` are moved to `failed`.

## Wiki Compiler Lifecycle

The compiler skeleton is intentionally conservative:

1. Create `wiki_compile_job` as `pending`.
2. Mark job `processing`.
3. Query RAG evidence using default `hybrid` mode.
4. Render deterministic Markdown sections:
   - Summary
   - Key Concepts
   - Source-backed Claims
   - Related Pages
   - Open Questions
5. Create or update the target wiki page through `WikiService`.
6. Persist claims in `wiki_claim`.
7. Persist provenance in `wiki_claim_source`.
8. Mark compile job `succeeded`, or `failed` with the error text.

The compiler does not invent citations. If RAG evidence lacks structured
source, chunk, entity, or relation IDs, the raw metadata is preserved in
`wiki_claim_source.locator`.

## S3 Asset Strategy

The S3 layer keeps raw and derived data separate:

- `rag-raw` stores the original document exactly once per
  `{tenant_id}/{source_id}/{filename}`.
- `rag-assets` stores parser output under a stable `output/` prefix.

Content type is detected with Python `mimetypes` and sent as S3 object
metadata. Public URLs are constructed from the configured endpoint, bucket, and
object key; production deployments may replace this with signed URLs or a CDN.

## PostgreSQL Schema Explanation

### `wiki_page`

One row per logical wiki page. `(tenant_id, slug)` is unique. The page stores
title, type, status, and `current_revision_id`.

### `wiki_revision`

Immutable page revisions. `(page_id, revision_no)` is unique. Markdown is stored
in `content`; optional structured content can be stored in `content_json`.

### `wiki_link`

Extracted wikilinks for backlink queries. Each row stores a source page and a
target slug. Target pages do not need to exist.

### `wiki_claim`

Atomic source-backed or source-seeking claims for a page revision. The
`support_status` field is enum-like text and currently supports rule-based
validation.

### `wiki_claim_source`

Claim provenance. Structured references such as source ID, chunk ID, entity ID,
relation ID, asset URL, page number, bounding box, and quote are stored when
available. `locator` stores arbitrary raw metadata.

### `ingest_job`

Ingest lifecycle row keyed by `(tenant_id, source_id)`. Status is constrained to
`pending`, `processing`, `succeeded`, or `failed`. Errors are persisted in
`error`. Worker retry state is stored in `attempt_count`, `max_attempts`,
`claimed_at`, `heartbeat_at`, `locked_by`, and `next_attempt_at`.

### `wiki_compile_job`

Compile lifecycle row for source or topic compilation. Status values match
`ingest_job`.

### `wiki_validation_result`

Persisted validation findings for a page revision. Rows include validator name,
severity, message, and JSON metadata.
