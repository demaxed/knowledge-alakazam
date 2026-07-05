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
