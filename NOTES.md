# Project Notes

This file is the running task log for the project. Codex must append notes here after every implementation task.

## Note-Taking Rule

After each task, append a concise entry with:

- Task number and name.
- Date completed.
- Files created or changed.
- Commands run.
- Verification results.
- Follow-up work, known limitations, or operational notes.

Keep entries short and factual. Do not store secrets in this file.

## 2026-07-06 - Task 8: Ingest Worker

- Added `worker/ingest_worker.py` with a polling async worker, `FOR UPDATE SKIP LOCKED` job claiming, raw S3/MinIO download, ingest processing, final status persistence, and SIGINT/SIGTERM shutdown handling.
- Added optional Docker Compose `worker` profile and documented `uv run python -m worker.ingest_worker`.
- Added `WORKER_POLL_INTERVAL_SECONDS` setting and `.env.example` entry.
- Refactored `DocumentIngestService` so the worker can process an already-staged raw document without re-uploading it.
- Added worker tests for claim SQL, raw path mapping, success, processing failure, invalid raw key failure, and no-job polling.
- Verification passed: `docker compose config --quiet`, `uv run ruff check .`, `uv run pytest`, and `uv run mypy app wiki worker`.
- Follow-up: retry attempts are not implemented yet because `ingest_job` has no attempt counter or max-attempt columns.

## 2026-07-06 - Instructions Cleanup: Remove AGENT.md

- Removed the compatibility `AGENT.md` file at the project owner's request.
- Kept `AGENTS.md` as the only Codex instruction file and removed the synchronization note that referred to `AGENT.md`.
- Verification passed: `uv run ruff check .`, `uv run pytest`, and `uv run mypy app wiki worker`.

## 2026-07-06 - Task 9: llm-wiki Compiler Skeleton

- Added `wiki/compiler.py` with `WikiCompiler`, RAG evidence querying, deterministic Markdown page rendering, claim/source persistence, fallback provenance handling, and compile-job status transitions.
- Added `WikiRepository` compile-job methods for pending, processing, succeeded, and failed states.
- Added `POST /wiki/compile` plus request/response schemas for source-only, topic-only, and topic-with-source compile requests.
- Documented compiler usage and the provenance limitation when RAG metadata lacks structured chunk/entity IDs.
- Added compiler tests for successful source compilation, fallback raw-metadata provenance, failed job persistence, and the compile API.
- Verification passed: `uv run ruff check .`, `uv run pytest`, and `uv run mypy app wiki worker`.
- Follow-up: the compiler still relies on the RAG runtime's returned metadata shape; richer page planning and citation extraction should be added once real LightRAG/RAG-Anything evidence payloads are observed.

## 2026-07-06 - Task 10: Validation and Observability

- Added `wiki/validators.py` with broken wikilink validation, unsupported-claim and stale-page skeleton checks, duplicate slug/title validation, and a validation service that persists `wiki_validation_result` rows.
- Extended `WikiRepository` with validation result persistence/listing plus page and claim lookup helpers needed by validators.
- Added `POST /wiki/pages/{slug}/validate` and `GET /wiki/pages/{slug}/validation-results` with response schemas.
- Added structured JSON logging, request ID middleware, richer `/health` output, DB reachability checks, optional S3 health checks, RAG runtime status, ingest lifecycle logs, runtime initialization logs, and S3 upload count logs.
- Updated `.env.example`, README, health/config tests, and wiki validation tests.
- Verification passed: `uv run ruff check .` and `uv run pytest`.
- Follow-up: unsupported-claim validation is still rule-based on `support_status`; deeper evidence verification should be added after real RAG evidence payloads and citation metadata are observed.

## 2026-07-06 - Task 11: Final Hardening and Docs

- Reworked `README.md` into a final operator guide with architecture overview, uv and Docker Compose startup, migrations, ingest/query/wiki examples, worker usage, environment variable table, observability notes, and known limitations.
- Added `docs/architecture.md` covering components, data flow, storage model, ingest lifecycle, wiki compiler lifecycle, S3 asset strategy, and PostgreSQL schema explanation.
- Added `docs/operations.md` covering backups, embedding dimension immutability, PostgreSQL extensions, object storage lifecycle, reindexing, wiki compile replay, health checks, logging, local Compose operations, and secret handling.
- Added a `Makefile` with `format`, `lint`, `test`, `migrate`, and `docker-config` targets that wrap the existing `uv` and Docker Compose commands.
- Ran `uv run ruff format .`; it applied mechanical formatting to existing Python files.
- Verification passed: `docker compose config --quiet`, `uv run ruff check .`, `uv run pytest`, and `uv run mypy app wiki worker`.
- Live `docker compose up --build -d` verification was attempted but could not connect to the configured Docker daemon socket at `/Users/mademyanenko/.lima/avito/sock/docker.sock`.
- Follow-up: run `docker compose up --build` from an environment with the Docker daemon running, then apply migrations and check `http://127.0.0.1:8080/health`.

## 2026-07-06 - Docker Compose pgvector Startup Fix

- Fixed the custom PostgreSQL Docker image build by compiling pgvector with `OPTFLAGS=""`, matching pgvector's portable Docker build guidance and avoiding `Illegal instruction` crashes from `-march=native`.
- Diagnosed the local Docker failure: the default Docker context pointed at missing `/var/run/docker.sock`; `colima-avito` was the reachable context.
- Rebuilt and started `postgres`, `minio`, and `create-buckets` through `docker --context colima-avito compose`.
- Repaired the existing local Postgres volume by manually applying `/docker-entrypoint-initdb.d/001_extensions.sql` after the rebuild; verified `age:1.6.0` and `vector:0.8.4`.
- Files changed: `db/Dockerfile.postgres`, `NOTES.md`.
- Commands run: `docker context ls`, `docker --context colima-avito compose up --build -d postgres minio create-buckets`, `docker --context colima-avito compose logs`, `docker --context colima-avito compose up --build -d postgres`, `docker --context colima-avito compose exec -T postgres psql ...`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: Compose services are healthy (`postgres`, `minio`) or completed successfully (`create-buckets`); `uv run ruff check .`; `uv run pytest` with 46 passing tests.

## 2026-07-06 - Docker App pgvector Python Dependency

- Added the Python `pgvector` adapter to the `rag` optional dependency set so Docker app and worker images built with `INSTALL_RAG_EXTRAS=true` can load LightRAG `PGVectorStorage`.
- Rebuilt `knowledge-alakazam-app:local` through `docker --context colima-avito compose build app`; the build installed `pgvector==0.4.2`.
- Recreated the running app container and verified `pgvector` imports inside it.
- Verified container-internal `/health` returned `status: ok` with DB, S3, and enabled RAG runtime using `PGVectorStorage`.
- Files changed: `pyproject.toml`, `uv.lock`, `NOTES.md`.
- Commands run: `uv add --optional rag pgvector`, `docker --context colima-avito compose build app`, `docker --context colima-avito compose up -d app`, `docker --context colima-avito compose exec -T app python ...`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: Docker app import check for `pgvector`; container-internal `/health`; `uv run ruff check .`; `uv run pytest` with 46 passing tests.

## 2026-07-06 - Text Ingest Parser Fallback

- Added `app/rag_parsers.py` with a text-first RAG-Anything parser adapter that handles `.md` and `.txt` directly and delegates PDFs, images, and office files to the configured parser.
- Wrapped each RAG-Anything runtime parser in the adapter so Markdown sample ingest no longer fails during the MinerU startup preflight when the MinerU CLI is unavailable in the running environment.
- Documented the RAG-Anything 1.3.1 parser preflight behavior and the text-only fallback in `README.md`.
- Added focused tests for direct Markdown parsing, non-text delegation, idempotent runtime installation, and missing text files.
- Files changed: `app/rag_parsers.py`, `app/rag_runtime.py`, `tests/test_rag_parsers.py`, `README.md`, `NOTES.md`.
- Commands run: `uv run python -c ...` package/API checks, `uv run mineru --version`, `uv run ruff format app/rag_parsers.py app/rag_runtime.py tests/test_rag_parsers.py`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: local package inspection confirmed `raganything==1.3.1` and MinerU CLI behavior; `uv run ruff check .`; `uv run pytest` with 50 passing tests.
- Follow-up: non-text documents still require the selected parser runtime dependencies, such as MinerU for `PARSER=mineru`.

## 2026-07-06 - RAG-Anything Auxiliary Cache Namespace Fix

- Pre-installed RAG-Anything `parse_cache` and `multimodal_status` auxiliary caches with LightRAG `JsonKVStorage` before `_ensure_lightrag_initialized()` runs.
- Avoided RAG-Anything creating unsupported `parse_cache` / `multimodal_status` namespaces through LightRAG `PGKVStorage`, which logs `Unknown namespace: parse_cache` during cache writes.
- Documented the RAG-Anything 1.3.1 and LightRAG `PGKVStorage` namespace mismatch in `README.md`.
- Added a focused runtime test proving RAG-Anything sees the pre-installed auxiliary caches before its initializer runs.
- Files changed: `app/rag_runtime.py`, `tests/test_rag_runtime.py`, `README.md`, `NOTES.md`.
- Commands run: `uv run python -c ...` package/API checks, `rg -n -uu ...` package source inspection, `uv run pytest tests/test_rag_runtime.py -q`, `uv run ruff format app/rag_runtime.py tests/test_rag_runtime.py`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: `tests/test_rag_runtime.py` with 5 passing tests; `uv run ruff check .`; `uv run pytest` with 51 passing tests.
- Follow-up: rebuild/restart any running Docker app or worker containers so they use the patched runtime code.

## 2026-07-06 - Separate Embedding Endpoint Configuration

- Added optional `EMBEDDING_BASE_URL` configuration, with `EMBEDDING_ENDPOINT_URL` and `EMBEDDING_ENDPOINT` aliases, so embeddings can use a separate OpenAI-compatible endpoint from LLM/VLM calls.
- Updated the OpenAI-compatible provider to pass `EMBEDDING_BASE_URL` to `openai_embed` and fall back to `OPENAI_BASE_URL` when it is unset.
- Documented the new environment variable in `.env.example`, `README.md`, and the reindex operations checklist.
- Added config and runtime tests covering environment loading, separate embedding endpoint routing, and fallback behavior.
- Files changed: `app/config.py`, `app/rag_runtime.py`, `.env.example`, `tests/test_config.py`, `tests/test_rag_runtime.py`, `README.md`, `docs/operations.md`, `NOTES.md`.
- Commands run: `uv run pytest tests/test_config.py tests/test_rag_runtime.py -q`, `uv run ruff format app/config.py app/rag_runtime.py tests/test_config.py tests/test_rag_runtime.py`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: targeted config/runtime tests with 9 passing tests; `ruff format` left files unchanged; `uv run ruff check .`; `uv run pytest` with 53 passing tests.
- Follow-up: set `EMBEDDING_BASE_URL` only when the embedding model is served from a different endpoint; otherwise existing `OPENAI_BASE_URL` deployments continue to work unchanged.

## 2026-07-06 - Makefile MinIO Clear Target

- Added `dc.clear_s3` to clear the configured MinIO raw/assets bucket contents through the Docker Compose `create-buckets` service and recreate the buckets if needed.
- Updated `.PHONY` to include the existing local Makefile targets plus `dc.clear_s3`.
- Files changed: `Makefile`, `NOTES.md`.
- Commands run: `make -n dc.clear_s3`, `docker compose config --quiet`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: Makefile dry-run produced the expected Compose command; Docker Compose config validation passed; `uv run ruff check .`; `uv run pytest` with 53 passing tests.
- Follow-up: `dc.clear_s3` clears only `S3_BUCKET_RAW` and `S3_BUCKET_ASSETS`; it does not remove other MinIO buckets or delete the `minio-data` volume.

## 2026-07-06 - README Image

- Added the requested external Alakazam image to the top of `README.md`.
- Files changed: `README.md`, `NOTES.md`.
- Commands run: `uv run ruff check .`, `uv run pytest`.
- Verification passed: `uv run ruff check .`; `uv run pytest` with 53 passing tests.
- Follow-up: none.

## 2026-07-06 - Local README Image Asset

- Downloaded the README Alakazam image into the project at `assets/alakazam.jpg`.
- Updated `README.md` to reference the local image path instead of the external URL.
- Files changed: `README.md`, `NOTES.md`, `assets/alakazam.jpg`.
- Commands run: `curl -L -o assets/alakazam.jpg ...`, `file assets/alakazam.jpg`, `ls -lh assets/alakazam.jpg`, `uv run ruff check .`, `uv run pytest`.
- Verification passed: `README.md` no longer contains the external image URL; `assets/alakazam.jpg` is a valid 800x600 JPEG; `uv run ruff check .`; `uv run pytest` with 53 passing tests.
- Follow-up: none.

## 2026-07-06 - Resolve CRITICAL-1 Wiki Compile Transaction

- Fixed `WikiRepository.transaction()` so SQLAlchemy `AUTOBEGIN` transactions opened by prior reads are committed or rolled back by the repository transaction boundary instead of being mistaken for caller-owned transactions.
- Preserved nested repository transactions and explicit caller-managed `BEGIN` transactions without forcing an unexpected commit.
- Added focused regression tests for autobegun commit, autobegun rollback, explicit external transactions, and normal `session.begin()` behavior.
- Files changed: `wiki/repository.py`, `tests/test_wiki_repository.py`, `NOTES.md`.
- Commands run: `uv run pytest tests/test_wiki_repository.py tests/test_wiki_compiler.py`, `uv run ruff check wiki/repository.py tests/test_wiki_repository.py`, `uv run ruff check .`, `uv run pytest`, `uv run mypy app wiki worker`.
- Verification passed: targeted wiki transaction/compiler tests with 8 passing tests; `uv run ruff check .`; `uv run pytest` with 57 passing tests; `uv run mypy app wiki worker`.
- Follow-up: consider applying the same transaction-origin pattern to `IngestJobRepository.transaction()` if future ingest flows perform standalone reads before job status writes on the same session.

## 2026-07-06 - Resolve HIGH-2 Ingest Worker Leases

- Added durable ingest job lease and retry metadata: `attempt_count`, `max_attempts`, `claimed_at`, `heartbeat_at`, `locked_by`, and `next_attempt_at`.
- Added an Alembic migration and model constraints/indexes for retry budgets and claimable job lookup.
- Updated the DB-backed worker queue to reclaim stale `processing` jobs, heartbeat active leases, prevent stale workers from writing final status after ownership is lost, and mark exhausted stale jobs `failed`.
- Reset retry/lease metadata when a new pending ingest job is created and routed max-attempts/lease settings through `pydantic-settings`.
- Documented `WORKER_JOB_LEASE_SECONDS` and `WORKER_JOB_MAX_ATTEMPTS` in `.env.example`, `README.md`, architecture notes, and operations notes.
- Files changed: `.env.example`, `README.md`, `app/api/ingest.py`, `app/config.py`, `app/ingest_service.py`, `docs/architecture.md`, `docs/operations.md`, `migrations/versions/20260706_0002_ingest_job_leases.py`, `tests/test_config.py`, `tests/test_ingest_worker.py`, `tests/test_wiki_models.py`, `wiki/models.py`, `worker/ingest_worker.py`, `NOTES.md`.
- Commands run: `uv run pytest tests/test_ingest_worker.py tests/test_wiki_models.py tests/test_config.py`, `uv run ruff check worker/ingest_worker.py app/ingest_service.py app/config.py app/api/ingest.py wiki/models.py tests/test_ingest_worker.py tests/test_wiki_models.py tests/test_config.py`, `uv run ruff check .`, `uv run pytest`, `uv run ruff format . --check`, `uv run ruff format .`, `uv run mypy app wiki worker`.
- Verification passed: targeted ingest worker/model/config tests with 16 passing tests; `uv run ruff check .`; `uv run pytest` with 60 passing tests; `uv run ruff format . --check`; `uv run mypy app wiki worker`.
- Follow-up: add a PostgreSQL integration test for two real workers competing over stale `processing` rows once a DB-backed integration suite exists.

## 2026-07-06 - Resolve HIGH-4 Async Blocking Ingest IO

- Added async offloading wrappers to `S3AssetStore` for raw uploads, output-tree uploads, and raw downloads while preserving the existing synchronous API.
- Updated the async ingest service to run local staging/hash/copy work, raw S3 uploads, output directory creation, and parsed asset uploads off the event-loop thread.
- Updated the FastAPI ingest route to create temp directories, write multipart upload chunks, close files, and remove temp trees through `asyncio.to_thread`.
- Updated the ingest worker to offload raw S3 downloads and reuse the service's offloaded parsed asset upload path.
- Added regression tests that verify S3, service, worker, and upload staging operations run through the threaded offload path, including temp cleanup after upload cancellation.
- Files changed: `app/api/ingest.py`, `app/ingest_service.py`, `app/s3_assets.py`, `worker/ingest_worker.py`, `tests/test_ingest_api.py`, `tests/test_ingest_service.py`, `tests/test_ingest_worker.py`, `tests/test_s3_assets.py`, `NOTES.md`.
- Commands run: `uv run pytest tests/test_s3_assets.py tests/test_ingest_service.py tests/test_ingest_worker.py tests/test_ingest_api.py`, `uv run ruff check app/s3_assets.py app/ingest_service.py app/api/ingest.py worker/ingest_worker.py tests/test_s3_assets.py tests/test_ingest_service.py tests/test_ingest_worker.py tests/test_ingest_api.py`, `uv run ruff check .`, `uv run pytest`, `uv run ruff format . --check`, `uv run mypy app wiki worker`.
- Verification passed: targeted ingest/S3/API tests with 27 passing tests; `uv run ruff check .`; `uv run pytest` with 66 passing tests; `uv run ruff format . --check`; `uv run mypy app wiki worker`.
- Follow-up: consider moving raw document upload fully out of the HTTP request path if asynchronous ingest response latency becomes a production bottleneck.
