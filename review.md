# Code Review

## 1. Executive Summary

The repository is a compact, production-shaped FastAPI backend for multimodal RAG ingest, query, and PostgreSQL-backed llm-wiki storage. The codebase has a clear module split, strong use of `pydantic-settings`, async SQLAlchemy, documented operational constraints, and a fast unit test suite. `uv run ruff check .`, `uv run pytest`, and `docker compose config --quiet` all pass in the current workspace.

The main risk is transaction correctness around the wiki compiler. A SQLAlchemy read can open an implicit transaction before later write operations enter the repository transaction helper. Because the helper skips commit when `session.in_transaction()` is true, the compile endpoint can return a successful response while rolling back the generated page, claims, and final job status when the request session closes.

The next most important risks are production security and reliability gaps: no authentication or authorization, caller-controlled `tenant_id`, unbounded arbitrary uploads, blocking S3/file operations inside async request paths, and ingest jobs that can remain stuck in `processing` after worker crashes or cancellation. The test suite is useful but mostly unit-level and uses in-memory repositories, so it does not exercise the transaction behavior, PostgreSQL constraints, S3 behavior, or real deployment flow.

Most important recommendations:

1. Fix the wiki compiler transaction boundary and add a real database integration test for `POST /wiki/compile`.
2. Add authentication, authorization, tenant scoping, upload limits, and file type policy before any shared or production deployment.
3. Add job leases/retries for workers and make ingest I/O non-blocking or move it fully off the API event loop.
4. Add PostgreSQL-backed integration tests for migrations, repository concurrency, and transaction behavior.
5. Include migrations in the container or provide a first-class migration job.

## 2. Repository Overview

Project purpose:

Knowledge Alakazam is a FastAPI backend for multimodal document ingest, RAG querying, and canonical llm-wiki persistence. It is oriented around RAG-Anything, LightRAG, PostgreSQL with pgvector and Apache AGE, S3-compatible object storage, and PostgreSQL-backed wiki state.

Main technology stack:

- Python 3.11+ project managed with `uv`.
- FastAPI and Pydantic v2 for HTTP APIs and request/response schemas.
- `pydantic-settings` for configuration.
- Async SQLAlchemy and asyncpg for PostgreSQL access.
- Alembic for migrations.
- boto3 for S3-compatible storage.
- Optional RAG runtime packages: LightRAG and RAG-Anything.
- Docker Compose local stack with PostgreSQL, pgvector, Apache AGE, MinIO, API, and optional worker.

Entrypoints:

- API app: `app/main.py`, `app = create_app()`.
- API routers: `app/api/health.py`, `app/api/ingest.py`, `app/api/query.py`, `app/api/wiki.py`.
- Worker: `python -m worker.ingest_worker`.
- Migrations: `uv run alembic upgrade head`.
- Local app command: `uv run uvicorn app.main:app --reload`.

Key directories and modules:

- `app/`: FastAPI application, settings, DB lifecycle, schemas, RAG runtime, ingest, S3 adapter, observability.
- `wiki/`: SQLAlchemy models, repository, service workflows, compiler, validators.
- `worker/`: async ingest worker and DB-backed job claiming.
- `migrations/`: Alembic migration scripts.
- `db/`: PostgreSQL image and extension initialization.
- `tests/`: unit-level tests for config, routes, ingest, S3, RAG runtime wrappers, wiki services, compiler, and validators.
- `docs/`: architecture and operations documentation.

Overall runtime/data flow:

- API startup initializes settings, JSON request logging, DB engine/session factory, and a lazy tenant-scoped `RAGRuntimeRegistry`.
- `/ingest` stages uploaded files locally, writes or updates an `ingest_job`, uploads raw documents to S3, optionally runs RAG-Anything synchronously, uploads parsed assets, and marks the job final.
- With `INGEST_SYNC=false`, `/ingest` creates a pending job for `worker/ingest_worker.py`. The worker claims pending jobs using `FOR UPDATE SKIP LOCKED`, downloads the raw object, runs the same parser/RAG path, uploads assets, and marks success or failure.
- `/query` lazily initializes the tenant RAG runtime and delegates to RAG-Anything.
- `/wiki/pages` creates or updates canonical wiki pages and appends revisions in PostgreSQL.
- `/wiki/compile` queries RAG evidence, renders deterministic Markdown, creates a wiki revision, stores claims/provenance, and records a compile job.
- `/wiki/pages/{slug}/validate` runs rule-based validators and persists validation results.

## 3. Strengths

- Clear architectural split between API routes, runtime adapters, ingest orchestration, S3 storage, wiki repository, wiki service, compiler, and validators.
- Configuration is centralized in `app/config.py` with `pydantic-settings`; sensitive fields use `SecretStr` where appropriate.
- Database access uses async SQLAlchemy and explicit repository methods rather than scattering SQL throughout routes.
- Multi-tenancy is modeled consistently with `tenant_id` on primary app-owned tables and API payloads.
- `source_id` is used as the stable ingest/job identifier.
- RAG runtime imports are isolated behind `app/rag_runtime.py`, so tests and local boot can run with runtime disabled.
- The RAG package/API mismatch discovered during implementation is documented in `README.md`.
- Ingest failures are persisted to `ingest_job.error` in the implemented ingest paths.
- The worker claim query uses `FOR UPDATE SKIP LOCKED`, which is the right direction for multiple worker processes.
- S3 object keys are deterministic and separated between raw documents and derived assets.
- Structured JSON logging exists for API requests and app-owned events, with simple secret-field redaction.
- Documentation is unusually complete for a young repository: README, architecture, operations, environment variables, known limitations, and local run paths are all present.
- Tests are fast and cover many pure service behaviors, RAG runtime wrappers, parser adapter logic, S3 key mapping, job transitions, and route error mapping.
- Dockerfile runs the app as a non-root user.
- `uv.lock` is present and dependency management follows the repository rule to use `uv`.

## 4. Critical Issues

### CRITICAL-1: Wiki compile can return success while generated data is rolled back

* **Location:** `wiki/compiler.py:224-267`, `wiki/compiler.py:287-298`, `wiki/repository.py:55-62`, `app/db.py:57-58`
* **Problem:** `WikiCompiler.update_existing_page_with_evidence()` resolves the existing page title before creating/updating the page. That read path calls `WikiService.get_page()`, which performs SQLAlchemy `SELECT` operations outside an explicit transaction. SQLAlchemy sessions enter an implicit transaction after a read. Later, `WikiService.create_or_update_page()` and `WikiService.add_claim_with_sources()` call `WikiRepository.transaction()`, but the helper only yields when `session.in_transaction()` is already true and therefore does not commit. The request dependency in `app/db.py` closes the session without an explicit commit.
* **Impact:** In the production DB-backed path, `POST /wiki/compile` can return an in-memory response with `status="succeeded"` while the generated page revision, links, claims, claim sources, and final compile job status are not committed. The compile job can remain durably stuck at `processing`, and the canonical wiki page may be missing or stale even though the API reported success. This bug is not caught by the current tests because compiler tests use `InMemoryWikiRepository` and `NoopTransaction`, which do not emulate SQLAlchemy autobegin/rollback behavior.
* **Recommendation:** Make compiler persistence a single explicit unit of work that starts before any reads and commits after page, revision, links, claims, provenance, and final job status are written. Avoid calling write methods after unscoped reads on the same session. Add a PostgreSQL-backed integration test for `POST /wiki/compile` that asserts the compile job, page revision, links, claims, and claim sources are committed after the response. Consider replacing the repository transaction helper with a stricter unit-of-work abstraction so an implicit read transaction cannot silently suppress commit.
* **Confidence:** High

## 5. High Priority Issues

### HIGH-1: Authentication and authorization are not implemented

* **Location:** `app/main.py:35-39`, `app/api/query.py:29-40`, `app/api/ingest.py:75-125`, `app/api/wiki.py:58-226`, `README.md:417-419`
* **Problem:** All API routes are registered without authentication or authorization dependencies. `tenant_id` is accepted from the caller in request bodies or query parameters and is used as a logical isolation key, not a verified security boundary.
* **Impact:** If this service is exposed beyond a private local environment, any caller can ingest documents, query tenant indexes, create or overwrite wiki pages, compile wiki content, validate pages, and read page contents by choosing a `tenant_id`. This is a direct cross-tenant data isolation and data exfiltration risk.
* **Recommendation:** Add an authentication dependency at the router or application level. Derive allowed tenants from the authenticated principal rather than trusting payload `tenant_id`. Enforce authorization in one shared dependency or service boundary for all routes. Add tests that prove a caller cannot access another tenant's ingest jobs, RAG runtime, wiki pages, validation results, or compile jobs.
* **Confidence:** High

### HIGH-2: Ingest jobs can remain stuck in `processing` forever after crashes or cancellation

* **Location:** `worker/ingest_worker.py:67-74`, `worker/ingest_worker.py:81-91`, `worker/ingest_worker.py:161-189`, `wiki/models.py:193-213`
* **Problem:** The worker only claims jobs with `status == "pending"` and immediately marks them `processing`. There is no lease timestamp, heartbeat, retry counter, max attempts, stale-processing recovery, or dead-letter state. If the process exits, is killed, loses the DB connection, or is cancelled after claiming a job but before marking it succeeded/failed, that job will not be selected again.
* **Impact:** Documents can stop ingesting permanently with no automatic recovery. Operators would need manual database intervention to reset rows. This also affects deployments and rolling restarts because in-flight jobs may be stranded.
* **Recommendation:** Add fields such as `attempt_count`, `max_attempts`, `claimed_at`, `heartbeat_at`, `locked_by`, and possibly `next_attempt_at`. Claim pending jobs and stale processing jobs whose lease expired. Mark cancellation paths intentionally, or let leases expire and retry. Add tests for crash recovery, retry exhaustion, and multiple workers.
* **Confidence:** High

### HIGH-3: The ingest endpoint accepts unbounded arbitrary uploads

* **Location:** `app/api/ingest.py:75-84`, `app/api/ingest.py:128-135`, `app/ingest_service.py:368-402`
* **Problem:** `_save_upload_to_temp()` reads the entire multipart upload to disk in 1 MiB chunks without enforcing a maximum file size, tenant quota, source quota, content type allowlist, extension allowlist, or parser eligibility policy. The route accepts any `UploadFile` and only sanitizes the final filename path component.
* **Impact:** A client can exhaust disk space, force expensive parsing of unsupported or malicious files, create very large S3 objects, or consume CPU/memory through parser behavior. Combined with missing authentication, this is a production denial-of-service risk.
* **Recommendation:** Enforce request size limits at the reverse proxy and application boundary. Add settings for maximum upload bytes, allowed MIME types/extensions, per-tenant quotas, and parser-specific limits. Count bytes while streaming and abort when the limit is exceeded. Return a 413 or 415 response as appropriate. Add tests for oversized uploads, unsupported types, and safe cleanup of temporary files.
* **Confidence:** High

### HIGH-4: Synchronous file and S3 operations block async request handling

* **Location:** `app/api/ingest.py:132-134`, `app/ingest_service.py:315-321`, `app/ingest_service.py:362-366`, `app/s3_assets.py:95-173`, `app/s3_assets.py:180-197`
* **Problem:** The FastAPI route and async ingest service perform blocking filesystem copies/writes and boto3 `upload_file()`/`download_file()` calls directly inside async code. `create_pending_job()` also uploads the raw document synchronously before returning 202.
* **Impact:** Large uploads, slow object storage, or many parsed assets can block the event loop and degrade unrelated API requests. The service may appear async but behave like a single-threaded blocking server under ingest load.
* **Recommendation:** Move blocking filesystem and boto3 operations to `asyncio.to_thread()` or a dedicated thread pool, or use an async S3 client. Prefer making the API only stage metadata and enqueue work, with heavy upload/parse/asset transfer handled by workers. Add load-oriented tests or benchmarks for concurrent health/query requests during ingest.
* **Confidence:** High

## 6. Medium Priority Issues

### MEDIUM-1: Check-then-insert persistence paths are race-prone

* **Location:** `app/ingest_service.py:123-152`, `wiki/service.py:171-187`, `wiki/repository.py:130-160`, `wiki/repository.py:424-430`
* **Problem:** Several write paths first query for existing state and then insert or update without using PostgreSQL atomic upsert, row locks, advisory locks, or retry-on-unique-violation logic. Examples include `IngestJobRepository.upsert_job()`, wiki page create-or-update by `(tenant_id, slug)`, and revision numbering via `max(revision_no) + 1`.
* **Impact:** Concurrent requests for the same `(tenant_id, source_id)` or `(tenant_id, slug)` can produce `IntegrityError` responses. Concurrent revision creation can choose the same next revision number, causing failures or retries at the wrong layer. These bugs are likely under API retries, browser double-submit, multiple workers, or parallel compile jobs.
* **Recommendation:** Use PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` for ingest jobs and wiki page upserts. For revisions, lock the page row before computing the next revision number, use a per-page sequence/counter, or retry safely on unique constraint violations. Add DB-backed concurrency tests that run parallel requests against the same tenant/source/page.
* **Confidence:** High

### MEDIUM-2: Wiki compiler writes page content and claims in separate transactions

* **Location:** `wiki/compiler.py:245-267`, `wiki/service.py:171-201`, `wiki/service.py:268-298`
* **Problem:** Even after fixing the critical implicit transaction issue, compiler persistence is split across `create_or_update_page()` and one `add_claim_with_sources()` call per claim. Each service method owns its own transaction. A failure while adding claim N can occur after the page revision and earlier claims have already committed.
* **Impact:** A failed compile can leave a current generated page with missing or partial provenance, while the compile job is marked failed. Users may read the page as canonical even though its source-backed claims are incomplete.
* **Recommendation:** Persist the compile output as one atomic transaction, or introduce a staging status for generated revisions and publish only after all links, claims, and claim sources are successfully written. Add a test where claim insertion fails and assert the visible current revision does not advance.
* **Confidence:** High

### MEDIUM-3: Re-ingest can publish stale parsed assets

* **Location:** `app/ingest_service.py:354-366`, `app/s3_assets.py:130-173`
* **Problem:** `process_prepared_document()` creates the output directory with `exist_ok=True` and then uploads the entire existing `RAG_OUTPUT_DIR/{tenant_id}/{source_id}` tree. It does not clear the output directory before parsing, and it does not delete stale S3 asset keys.
* **Impact:** Re-ingesting the same `source_id` after parser behavior changes or after a document has fewer derived assets can re-upload old local files and leave stale objects in S3. Wiki provenance or UI clients can reference assets that were not produced by the latest ingest.
* **Recommendation:** Use a fresh versioned output prefix per ingest job or clear the tenant/source output directory before processing. Track an asset manifest for each ingest and delete or supersede stale S3 keys. Include regression tests where the second ingest produces fewer assets than the first.
* **Confidence:** High

### MEDIUM-4: Tenant runtime cache is unbounded

* **Location:** `app/rag_runtime.py:359-384`
* **Problem:** `RAGRuntimeRegistry` stores one initialized runtime per tenant workspace in an in-memory dictionary with no capacity limit, TTL, idle cleanup, tenant allowlist, or memory accounting.
* **Impact:** In a long-running process with runtime enabled, arbitrary or high-cardinality tenant IDs can create many LightRAG/RAG-Anything runtime objects, local workspaces, caches, and backend resources. With missing auth, this can be abused as a memory and connection exhaustion vector.
* **Recommendation:** Derive tenant IDs from authorized principals, reject unknown tenants, and add a bounded cache with idle eviction and metrics. Consider explicit runtime lifecycle management per deployment rather than lazy creation for unbounded tenant strings.
* **Confidence:** High

### MEDIUM-5: Container image does not include migrations or a migration job

* **Location:** `Dockerfile:31-33`, `docker-compose.yml:70-100`, `README.md:111-115`
* **Problem:** The application image copies `app`, `wiki`, and `worker`, but not `migrations` or `alembic.ini`. Docker Compose starts the app after PostgreSQL and MinIO are healthy, but it does not run migrations. The README instructs running `uv run alembic upgrade head` from the host.
* **Impact:** A containerized deployment cannot apply migrations from the app image, and the app can start against an unmigrated database. This makes local Docker less production-like and creates deployment drift between image contents and schema management.
* **Recommendation:** Include `migrations/` and `alembic.ini` in a migration-capable image, or define a dedicated migration job/service using the same build artifact. Gate app startup on successful migrations in local Compose or document a production migration workflow with explicit ownership.
* **Confidence:** High

### MEDIUM-6: Domain values are mostly free text and weakly validated

* **Location:** `app/schemas.py:51-70`, `wiki/models.py:56-67`, `wiki/models.py:153-160`, `wiki/models.py:227-233`, `wiki/models.py:263-266`
* **Problem:** Several domain fields are accepted and stored as arbitrary strings, including wiki `page_type`, page `status`, revision `content_format`, revision `author_type`, claim `support_status`, and validation `severity`. The database has check constraints for job statuses only.
* **Impact:** Invalid values can enter the canonical store through API or internal calls and later break response casting, validation behavior, filtering, or compatibility with future clients. For example, `WikiValidationResultResponse` only accepts `info`, `warning`, or `error`, but the table does not enforce that.
* **Recommendation:** Define shared `Literal` or Enum types for domain values, validate them in Pydantic request models, and add PostgreSQL check constraints. Include migration tests and negative API tests for invalid values.
* **Confidence:** High

### MEDIUM-7: Test coverage is mostly unit-level and misses the highest-risk behavior

* **Location:** `tests/test_wiki_compiler.py:20-61`, `tests/test_wiki_service.py:28-51`, `tests/test_ingest_service.py:20-48`, `tests/test_s3_assets.py:29-72`
* **Problem:** The test suite uses in-memory repositories and fake S3/runtime objects for most behavior. This keeps tests fast, but it does not exercise SQLAlchemy transaction semantics, Alembic migrations, PostgreSQL constraints, `FOR UPDATE SKIP LOCKED` behavior against a real database, real S3-compatible object storage, or container startup.
* **Impact:** The critical compiler transaction bug can pass all tests. Concurrency, migration drift, object storage behavior, and DB constraint failures are likely to be found late.
* **Recommendation:** Keep the fast unit tests, but add a smaller integration suite using PostgreSQL and MinIO from Docker Compose or testcontainers. Prioritize tests for compile persistence, concurrent page/revision creation, ingest job claiming/recovery, migrations from empty DB, and S3 upload/download error paths.
* **Confidence:** High

### MEDIUM-8: RAG runtime initialization does not clean up partially initialized resources on failure

* **Location:** `app/rag_runtime.py:220-263`, `app/rag_runtime.py:329-338`
* **Problem:** `RAGRuntime.initialize()` sets `self.lightrag` and initializes storages before creating/configuring RAG-Anything and auxiliary caches. If a later step raises or the task is cancelled, partially initialized storages can remain attached to the runtime object with `_initialized=False`, and no cleanup path runs until shutdown.
* **Impact:** Repeated initialization failures can leak connections, file handles, local cache state, or package-owned resources. Subsequent calls may retry initialization on a partially initialized object.
* **Recommendation:** Wrap initialization after resource creation in `try/except BaseException`, finalize any partially initialized storages, reset `self.lightrag` and `self.rag_anything`, then re-raise. Add tests for failures after `initialize_storages()` and during auxiliary cache setup.
* **Confidence:** Medium

## 7. Low Priority Issues / Maintainability Notes

### LOW-1: `mypy` configuration does not run cleanly in the current environment

* **Location:** `pyproject.toml:47-54`, `tests/test_rag_runtime.py:20-26`, `tests/test_query.py:9-15`, `tests/test_ingest_api.py:14-24`
* **Problem:** `uv run mypy app wiki worker tests` fails before checking project code because installed NumPy stubs use Python 3.12 syntax while `pyproject.toml` sets `python_version = "3.11"`. Running `uv run mypy --python-version 3.12 app wiki worker` succeeds for production code, but including tests reports 30 typing errors mostly around broad `dict[str, object]` settings factories and fake protocol types.
* **Impact:** The project has a mypy configuration but no reliable type-check command for the whole repository in the current environment. A future CI job that runs plain `uv run mypy ...` would fail.
* **Recommendation:** Decide whether mypy is a supported verification target. If yes, add a Make/CI target, align the configured Python version with the active type-check environment or pin incompatible stubs, and clean up test helper typing. If no, remove or relax misleading strict settings.
* **Confidence:** High

### LOW-2: Worker logs do not use the same JSON logging configuration as the API

* **Location:** `worker/ingest_worker.py:221-224`, `app/observability.py:119-138`
* **Problem:** The API configures structured JSON logging via `configure_logging()`, but the worker uses `logging.basicConfig(level=settings.log_level)`.
* **Impact:** Worker logs will have a different format, less consistent redaction behavior, and poorer compatibility with log ingestion dashboards than API logs.
* **Recommendation:** Reuse `app.observability.configure_logging(settings)` in the worker CLI and keep worker event names/extra fields consistent with API ingest events.
* **Confidence:** High

### LOW-3: Some container image tags and tooling sources are not pinned

* **Location:** `Dockerfile:20`, `docker-compose.yml:30`, `docker-compose.yml:50`
* **Problem:** The Dockerfile copies `uv` from `ghcr.io/astral-sh/uv:latest`, and Compose uses `minio/minio:latest` and `minio/mc:latest`.
* **Impact:** Builds can change behavior over time without a code change, making reproducibility and incident rollback harder. It also increases supply-chain review noise.
* **Recommendation:** Pin image tags or digests for build tools and services. Review and update them intentionally through dependency maintenance.
* **Confidence:** High

### LOW-4: Health status is always returned with HTTP 200 and there is no readiness/liveness split

* **Location:** `app/api/health.py:21-33`, `app/api/health.py:92-98`, `app/api/health.py:111-115`
* **Problem:** `/health` returns a body status of `ok` or `degraded`, but the route always returns HTTP 200. There are no separate liveness and readiness endpoints.
* **Impact:** Orchestrators and load balancers that rely only on status codes may continue sending traffic to an instance with an unreachable database or degraded dependencies.
* **Recommendation:** Add separate `/live` and `/ready` endpoints or return non-2xx for readiness failures. Keep a body-level component report for humans and dashboards.
* **Confidence:** High

### LOW-5: CI/CD configuration is absent

* **Location:** Repository root
* **Problem:** No CI workflow files are present. The repository has local commands and Make targets, but no automated enforcement for lint, tests, migrations, Docker Compose validation, or type checking.
* **Impact:** Quality gates depend on local discipline and can drift between contributors. Important checks such as migration smoke tests and Docker config validation may be skipped.
* **Recommendation:** Add a CI workflow that runs `uv sync --frozen`, `uv run ruff check .`, `uv run pytest`, `docker compose config --quiet`, and eventually a PostgreSQL integration test job. Add mypy only after resolving the current mypy issues.
* **Confidence:** High

### LOW-6: Optional RAG/runtime dependency boundaries are not fully clean

* **Location:** `pyproject.toml:6-24`, `Dockerfile:12-18`, `README.md:62-66`, `README.md:127-136`
* **Problem:** LightRAG and RAG-Anything are optional under `[project.optional-dependencies].rag`, but `mineru` is a base dependency and OCR/document tooling (`libreoffice`, `poppler-utils`, `tesseract-ocr`) is installed in the base image even when `INSTALL_RAG_EXTRAS=false`.
* **Impact:** The "base API" image remains heavier and has a larger dependency and security update surface than expected for runtime-disabled deployments.
* **Recommendation:** Revisit whether parser packages and system OCR/document tooling should be part of the `rag` extra and only installed in worker/RAG images. If they must stay in the base image, update the docs to make that tradeoff explicit.
* **Confidence:** Medium

## 8. Architecture Review

Separation of concerns is generally strong. API routes translate HTTP concerns into service calls, services coordinate workflows, repositories own persistence operations, and adapters isolate RAG and S3 package APIs. This keeps most modules understandable and testable.

The most significant architectural smell is transaction ownership. Repository methods expose a `transaction()` helper, but higher-level workflows sometimes perform reads and writes across multiple service calls. SQLAlchemy's implicit transaction behavior makes this fragile. Transaction boundaries should be owned by explicit workflow-level units of work, especially for compile and ingest lifecycles.

The dependency direction is mostly clean: `app` owns runtime/S3/API concerns; `wiki` owns domain persistence and workflows; `worker` composes app services. One boundary concern is that `wiki.compiler` imports `app.rag_runtime.RAGQueryResult`, which makes the wiki package depend on an app runtime DTO. A smaller protocol-local result type would make `wiki` more independent.

Extensibility is good for:

- adding new route modules;
- swapping RAG providers inside `app/rag_runtime.py`;
- adding validators through `WikiValidationService`;
- adding S3-compatible implementations behind `S3AssetStore`;
- extending wiki repositories with explicit methods.

Architectural improvements:

- Introduce a real unit-of-work abstraction for DB-backed workflows.
- Make compile persistence atomic and stage generated revisions before publishing.
- Add explicit tenancy/auth dependencies near route boundaries.
- Add an asynchronous job model for compile as well as ingest if compile remains long-running.
- Split "API-only" and "RAG/worker" dependency and container profiles if production deploys them separately.
- Add integration tests that run the architecture as deployed: FastAPI plus PostgreSQL plus MinIO.

## 9. Security Review

Secrets:

- `.env` is ignored by Git, and `.env.example` contains documented local development defaults only.
- Settings use `SecretStr` for OpenAI, MinIO root password, and S3 secret key fields.
- JSON logging redacts fields whose names look secret-like.
- The runtime writes PostgreSQL credentials into process environment variables for LightRAG in `app/rag_runtime.py:340-356`; this is not logged, but it is process-global.

Authentication and authorization:

- Not implemented. This is the largest security gap.
- `tenant_id` is entirely caller-controlled.
- README correctly documents that `tenant_id` is not a security boundary, but production deployment needs an actual auth boundary before exposing any API.

Input validation:

- Pydantic enforces non-empty values for many fields, but does not constrain length, charset, enum values, file size, file type, or content format sufficiently.
- Ingest path segment validation blocks slashes and relative markers, which helps path traversal, but does not enforce length or a narrow safe character set.

Unsafe deserialization:

- No unsafe deserialization was found in production code.

Command execution:

- No user-controlled runtime command execution was found in production code.
- Docker build clones pgvector from GitHub at build time; that is a build supply-chain concern, not a runtime command injection issue.

SQL injection:

- Repository code uses SQLAlchemy expression APIs and bound values. No direct user-controlled raw SQL was found.

SSRF/path traversal:

- Path traversal is partially mitigated for ingest staging by `_safe_path_segment()` and `_safe_filename()`.
- S3 endpoint URL is configuration-driven, not user-driven.
- Public asset URLs are constructed directly from configured endpoint, bucket, and key. Production should prefer private buckets plus signed URLs or CDN URLs.

Dependency vulnerabilities:

- No vulnerability audit was run. The environment has no configured dependency-audit command. Dependencies are locked in `uv.lock`, but several version specifiers in `pyproject.toml` are lower-bound-only.

Sensitive logging:

- API JSON logs avoid request bodies and redact obvious secret keys.
- Worker logging does not use the same JSON formatter/redaction setup.

## 10. Reliability & Error Handling

Good reliability decisions:

- Ingest failures are marked failed and persist `ingest_job.error` on normal exception paths.
- Worker processing catches ordinary exceptions and marks jobs failed.
- Health checks isolate database and optional S3 component status.
- Runtime disabled/configuration/unavailable errors are mapped to explicit 503 responses.

Main reliability gaps:

- The compile transaction bug can cause false success responses and rolled-back data.
- Worker jobs can be stuck in `processing` indefinitely after crash/cancellation.
- There are no retries, backoff, max attempts, or dead-letter states.
- Long-running query, ingest, parse, S3, and compile calls do not have explicit timeouts.
- RAG runtime partial initialization is not cleaned up on failure.
- Compile writes are not atomic across page revision, links, claims, provenance, and job status.
- Synchronous ingest can leave a job in `processing` if the request task is cancelled during parsing, because cancellation is not handled as a job lifecycle event.
- `create_pending_job()` writes a pending DB row before raw upload completes; a process crash in that window can leave a pending job whose object is not available.

Recommended reliability improvements:

- Add explicit workflow-level DB transactions for compiler operations.
- Add job lease/retry/dead-letter fields and stale job recovery.
- Add application-level timeouts around RAG query, parser processing, and S3 operations.
- Make cancellation behavior explicit: either mark cancelled jobs failed or let a lease expire for retry.
- Add recovery tooling for stuck jobs and failed compiles.

## 11. Performance & Scalability

Potential bottlenecks:

- Blocking boto3 and filesystem operations run inside async request code.
- Uploads are unbounded and copied through local disk before processing.
- `upload_output_tree()` traverses and uploads every file under a source output tree and returns all asset URLs in memory.
- `RAGRuntimeRegistry` can grow without bounds as tenant cardinality grows.
- API list endpoints for backlinks and validation results do not expose pagination.
- Compile and ingest are long-running synchronous HTTP operations when enabled.

Database usage:

- Indexes exist for tenant/status, backlinks, claims by page/revision, validation results, and jobs.
- There are useful uniqueness constraints for `(tenant_id, slug)`, `(page_id, revision_no)`, and `(tenant_id, source_id)`.
- Concurrency around those uniqueness constraints is not handled cleanly yet.
- `wiki_claim_source` has a `source_id` index but no tenant column, which can limit future tenant-scoped provenance queries unless joins are always used.

Scalability recommendations:

- Use async or threaded S3/file I/O and move heavy ingest to workers.
- Add pagination/cursors to list endpoints.
- Add runtime cache eviction and tenant authorization.
- Add background compile jobs if compile latency grows.
- Add explicit DB pool settings and observability for pool saturation.
- Add batching/manifests for asset upload and deletion.

## 12. Testing Review

Current verification results:

- `uv run ruff check .`: passed.
- `uv run pytest`: passed, 53 tests.
- `docker compose config --quiet`: passed.
- `uv run mypy app wiki worker tests`: failed before project checking because NumPy stubs use Python 3.12 syntax while mypy is configured for Python 3.11.
- `uv run mypy --python-version 3.12 app wiki worker`: passed.
- `uv run mypy --python-version 3.12 app wiki worker tests`: failed with 30 test typing errors.

Strengths:

- Tests are fast and isolated.
- Route tests verify dependency override wiring and key HTTP responses.
- Ingest service tests verify status transitions and failure persistence.
- Worker tests check `FOR UPDATE SKIP LOCKED` SQL generation and basic success/failure behavior.
- S3 tests cover key mapping, content types, bucket existence, missing files, and download parent creation.
- RAG runtime tests cover disabled mode, OpenAI-compatible embedding configuration, environment export, auxiliary cache setup, registry reuse, and workspace sanitization.
- Wiki service/compiler/validator tests cover core deterministic behavior.

Gaps:

- No real PostgreSQL integration tests.
- No Alembic migration smoke tests.
- No real S3/MinIO integration tests.
- No concurrency tests for upserts, revision numbering, or worker claiming.
- No tests for SQLAlchemy autobegin transaction behavior.
- No tests for API upload size limits because no limits exist.
- No tests for stale processing job recovery because no recovery exists.
- No end-to-end test for `/wiki/compile` persistence with a real DB session.
- No Docker image or migration workflow test.
- No security tests for tenant authorization because auth is absent.

Highest-value tests to add first:

1. DB-backed `/wiki/compile` persistence test.
2. DB-backed concurrent wiki revision creation test.
3. DB-backed concurrent ingest upsert test.
4. Worker stale processing recovery test after adding leases.
5. Oversized/unsupported upload API tests after adding upload policy.
6. Alembic upgrade-from-empty test.

## 13. Developer Experience

Readability:

- Code is generally direct, readable, and module names are clear.
- Service and repository method names are understandable.
- Dataclasses and protocols help make dependencies explicit.

Naming and modularity:

- The main modules map well to the runtime components.
- `upsert_page_revision()` is a misleading name for an append-only revision store because it can mutate an existing revision if called with `revision_no`. Consider splitting into `create_revision()` and a separate explicit repair/update method if mutation is ever needed.

Typing:

- Production code type-checks with mypy under Python 3.12.
- The configured mypy Python version and current dependency stubs are misaligned.
- Test helper typing needs cleanup if mypy is meant to cover tests.

Formatting/linting:

- Ruff configuration is present and `uv run ruff check .` passes.
- Make targets exist for format, lint, test, migration, and local helpers.

Local setup:

- README and docs are strong.
- Docker Compose validates.
- The app image does not include migrations, which weakens deployment ergonomics.
- `.env.example` is documented and `.env` is ignored.

Documentation:

- README documents architecture, commands, API examples, environment variables, RAG runtime notes, observability, and known limitations.
- `docs/architecture.md` and `docs/operations.md` are useful for onboarding.

CI/CD:

- No CI/CD workflow exists. This is the main developer-experience gap.

Dependency management:

- `uv` is used correctly as the primary package manager.
- `uv.lock` is committed.
- Runtime optionality should be tightened around parser/OCR dependencies if a lean API image is desired.

## 14. Recommended Action Plan

### Immediate

1. Fix the wiki compiler transaction boundary and add a PostgreSQL-backed regression test.
2. Add authentication and tenant authorization before exposing the service to shared users.
3. Add upload size/type limits and tenant quotas to `/ingest`.
4. Add ingest job leases and stale `processing` recovery.
5. Move blocking S3/file operations off the API event loop.

### Next

1. Replace check-then-insert paths with atomic PostgreSQL upserts or lock/retry logic.
2. Make compile page/revision/claim/provenance writes atomic.
3. Clear or version parser output directories and manage stale S3 assets.
4. Add DB and S3 integration tests for the highest-risk workflows.
5. Include migrations in the container image or add a dedicated migration job.
6. Add pagination to list-style wiki endpoints.
7. Add explicit RAG/query/ingest/compile timeouts.

### Later

1. Add runtime cache eviction and runtime lifecycle metrics.
2. Split API-only and RAG/worker container dependency profiles.
3. Pin Docker image tags/digests and add dependency audit tooling.
4. Align mypy config and decide whether tests are part of the type-check target.
5. Add CI/CD workflow with lint, tests, Docker Compose validation, and integration test stages.
6. Add richer observability: metrics, traces, queue depth, job latency, S3 timings, RAG timings, and DB pool metrics.

## 15. Appendix

Commands run during review:

- `rg --files`
- `git status --short`
- `find . -maxdepth 3 -type d`
- `docker compose config --quiet`
- `uv run ruff check .`
- `uv run pytest`
- `uv run mypy app wiki worker tests`
- `uv run mypy --python-version 3.12 app wiki worker`
- `uv run mypy --python-version 3.12 app wiki worker tests`

Verification summary:

- Ruff passed.
- Pytest passed: 53 tests.
- Docker Compose config validation passed.
- Production code mypy passed with `--python-version 3.12`.
- Repository-wide mypy is not currently clean due configuration/dependency-stub mismatch and test typing issues.

Workspace notes:

- Existing dirty file before review: `query_rag.sh`.
- This review did not modify production code.
- Review output was written to `review.md`.

Additional observations:

- `README.md` explicitly documents several limitations found in review, including missing auth, logical-only tenancy, missing retry counters, and rule-based validation. That is good transparency, but these items remain production blockers.
- The local `.env` file exists in the workspace and is ignored by Git. It was not treated as a source file for the review.
- The project currently has no critical issue around direct SQL injection based on inspected code because SQLAlchemy expression APIs are used for user-controlled values.
