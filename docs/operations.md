# Operations

This document covers operational concerns for local production-like development
and future production deployment. It does not replace environment-specific run
books, credentials management, monitoring, or backup policy.

## Backup Considerations

Back up PostgreSQL and object storage together. The database stores canonical
wiki state and references to object keys; S3/MinIO stores raw documents and
derived assets. Restoring only one side can leave dangling provenance or missing
documents.

Recommended backup scope:

- PostgreSQL database `rag`
- PostgreSQL roles and extension availability
- MinIO/S3 bucket `rag-raw`
- MinIO/S3 bucket `rag-assets`
- deployment configuration, excluding secrets
- model and embedding configuration used to build an index

PostgreSQL backups should be consistent snapshots or logical dumps taken with a
clear restore procedure. Object storage backups should preserve object keys,
metadata, and version history if versioning is enabled.

## Embedding Dimension Immutability

`EMBEDDING_DIM` is part of the physical vector index contract. Once documents
are indexed with a given dimension, do not change it in place.

Changing dimensions can break vector insertion or make query results invalid.
Treat a dimension change as a new index:

1. Choose the new embedding model and dimension.
2. Create a new LightRAG working directory or tenant workspace.
3. Recreate or migrate vector storage tables as required by LightRAG.
4. Replay ingest jobs or reprocess raw documents.
5. Recompile wiki pages if generated content depends on the old evidence.
6. Validate pages after recompilation.

Record the embedding model and dimension alongside deployment configuration so
operators can reproduce or audit the index later.

## PostgreSQL Extensions

The local Compose database creates:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS age;
```

The init script also loads AGE and sets a database-level search path with
`ag_catalog`, user schema, and `public`.

Operational notes:

- Extension initialization scripts run only when the PostgreSQL data directory is
  first created.
- For local extension changes, run `docker compose down -v` before rebuilding.
- For production, install and validate `vector` and `age` through the managed
  database process instead of relying on local Docker init scripts.
- Verify extension versions during upgrades.
- Test LightRAG graph behavior after any Apache AGE upgrade.

If the upstream Apache AGE image or pgvector source is unavailable, fallback
options are:

- build an internal PostgreSQL image that includes both extensions
- use a managed PostgreSQL provider that supports pgvector and run Apache AGE in
  a separate graph service if AGE is unavailable
- temporarily disable graph-backed runtime features while keeping the wiki and
  S3 layers functional

The main Compose setup remains the preferred local path.

## Object Storage Lifecycle

The service uses two buckets:

- `rag-raw`: original uploaded documents
- `rag-assets`: parsed images, table crops, equation crops, figures, and other
  extracted files

Recommended lifecycle policy:

- Keep raw documents at least as long as the index and wiki pages derived from
  them need to be reproducible.
- Keep parsed assets while claims, wiki pages, or UI references point to them.
- Enable bucket versioning for environments where accidental overwrite or
  deletion is a real risk.
- Use lifecycle expiration only after confirming that no active wiki provenance
  rows reference the keys.
- Use private buckets by default. Prefer signed URLs or a CDN layer for
  user-facing access.

Object key contracts:

- raw documents: `{tenant_id}/{source_id}/{filename}`
- parsed assets: `output/{tenant_id}/{source_id}/{relative_path}`

Do not change these mappings without a migration or compatibility layer.

## How To Reindex

Reindex when changing embedding endpoint, embedding model, embedding dimension,
parser behavior, LightRAG storage layout, or when recovering from index
corruption.

Suggested process:

1. Put ingest workers on hold.
2. Record current `EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`,
   parser settings, and LightRAG storage settings.
3. Back up PostgreSQL and object storage.
4. Create a new LightRAG workspace or clear the old LightRAG storage only after
   backup.
5. Reset selected `ingest_job` rows to `pending` through a controlled migration
   or operator script.
6. Start workers and replay jobs from raw S3 objects.
7. Monitor failed jobs and persisted `ingest_job.error`.
8. Re-run wiki compile jobs where generated pages depend on reindexed evidence.
9. Run wiki validation and inspect errors.

Ingest jobs include attempt counters and worker lease metadata. During replay,
reset selected rows to `pending` and confirm their `max_attempts` budget matches
the intended replay policy.

## How To Replay Wiki Compile Jobs

Compile jobs are stored in `wiki_compile_job`. The current API runs compile
synchronously through `POST /wiki/compile`; there is not yet a separate compile
worker.

Suggested replay options:

- Call `POST /wiki/compile` again for the same `tenant_id`, `source_id`, topic,
  and `target_slug`.
- Add an operator script that selects failed or stale compile jobs and invokes
  `WikiCompiler`.
- Add a future compile worker that claims compile jobs with
  `FOR UPDATE SKIP LOCKED`, mirroring the ingest worker pattern.

Before replay:

1. Confirm RAG runtime is enabled.
2. Confirm the target tenant index has been built.
3. Confirm model credentials are available.
4. Back up the wiki tables if replay may overwrite current revisions.

After replay:

1. Validate affected pages.
2. Review `wiki_claim_source` provenance quality.
3. Check for broken wikilinks and unsupported claims.

## Health Checks

`GET /health` reports:

- app status
- service and environment labels
- DB reachability
- optional S3 bucket reachability
- RAG runtime enabled or disabled status

Set `HEALTH_CHECK_S3=true` only when the app should fail or degrade health based
on object storage reachability. It is disabled by default so local development
does not require MinIO for basic app boot.

## Logging

Application logs are structured JSON for app-owned events. Request logging
includes request ID, method, path, status, and duration. Ingest, RAG runtime, and
S3 upload lifecycle events are logged without credentials or request bodies.

Do not log:

- API keys
- passwords
- authorization headers
- raw request bodies
- provider payloads that may include private document text

The JSON formatter redacts obvious secret-like keys, but callers should avoid
putting secrets into log extras in the first place.

## Local Docker Compose Operations

Start the stack:

```bash
docker compose up --build
```

Start the optional worker:

```bash
docker compose --profile worker up --build
```

Recreate state from scratch:

```bash
docker compose down -v
docker compose up --build
uv run alembic upgrade head
```

Check Compose syntax:

```bash
docker compose config --quiet
```

## Secret Handling

`.env.example` contains local development defaults only. Do not commit `.env` or
real credentials. Production secrets should come from the deployment platform's
secret manager or environment injection mechanism.

Settings fields that hold secrets use `SecretStr` where practical, and logs
must not include full settings dumps.
