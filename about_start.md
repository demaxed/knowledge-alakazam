You are basically at the first real end-to-end smoke test stage. The code, migrations, Docker Compose, ingest API, RAG query API, wiki compiler, and wiki read/validation APIs are in place. What is still needed is
  runtime configuration and a live run against your actual LLM-compatible endpoint.

  Where To Put Your LLM URL And Token

  Use a local .env file. Do not put real secrets into .env.example.

  Create .env from the template and set these values:

  cp .env.example .env

  Edit .env:

  RAG_RUNTIME_DISABLED=false

  OPENAI_BASE_URL=https://your-llm-gateway.example.com/v1
  OPENAI_API_KEY=your-api-auth-token

  LLM_MODEL=your-chat-model
  VISION_MODEL=your-vision-model
  EMBEDDING_MODEL=your-embedding-model
  EMBEDDING_DIM=1536

  The token goes into OPENAI_API_KEY even if you are not using OpenAI directly. The current runtime uses an OpenAI-compatible client, so OPENAI_BASE_URL points at your compatible gateway and OPENAI_API_KEY is the
  bearer/auth token used by that gateway.

  Be careful with EMBEDDING_DIM: it must match your embedding model and should be treated as immutable once documents are indexed. If your provider’s embedding model returns 1024-dimensional vectors, set
  EMBEDDING_DIM=1024 before the first ingest. If you ingest with the wrong dimension, the practical local fix is to create a new index or reset/reindex.

  Recommended First Launch Path

  For the first real test, I would run Postgres and MinIO in Docker, but run the FastAPI app on the host with uv. That path definitely loads .env through pydantic-settings.

  uv sync --extra rag
  docker compose up --build -d postgres minio create-buckets
  uv run alembic upgrade head
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8080

  Then check health:

  curl http://127.0.0.1:8080/health | python3 -m json.tool

  Expected useful signs:

  {
    "status": "ok",
    "components": {
      "db": {
        "status": "ok"
      },
      "rag_runtime": {
        "status": "enabled"
      }
    }
  }

  If you want S3 bucket checks included in health, set this in .env:

  HEALTH_CHECK_S3=true

  Then restart the API.

  Full Docker Compose Note

  The current docker-compose.yml uses .env.example as the app env_file. That is good for a non-secret example, but it means secrets placed only in .env are not automatically injected into the app container.

  For full Docker Compose testing, create a local docker-compose.override.yml like this:

  services:
    app:
      env_file:
        - .env.example
        - .env

    worker:
      env_file:
        - .env.example
        - .env

  Then set this in .env too:

  INSTALL_RAG_EXTRAS=true
  RAG_RUNTIME_DISABLED=false

  Run:

  docker compose up --build -d postgres minio create-buckets
  uv run alembic upgrade head
  docker compose up --build -d app

  Earlier, live docker compose up could not be verified in this workspace because the configured Docker daemon socket was unavailable. If you see a Docker socket error, fix Docker/Lima first, then retry.

  Upload 10 Files

  Put the 10 test documents in a local directory, for example:

  ./sample-docs/

  For a first run, keep INGEST_SYNC=true in .env. That makes each upload parse, index, upload assets, and persist the ingest job before the request returns.

  Batch upload 10 files:

  TENANT_ID=default
  n=0

  find ./sample-docs -maxdepth 1 -type f | sort | head -10 | while read -r file; do
    n=$((n + 1))
    source_id=$(printf "doc-%02d" "$n")

    echo "Uploading $file as $source_id"

    curl -sS -X POST http://127.0.0.1:8080/ingest \
      -F "tenant_id=${TENANT_ID}" \
      -F "source_id=${source_id}" \
      -F "file=@${file}" \
      | python -m json.tool
  done

  A successful ingest response should look structurally like:

  {
    "tenant_id": "default",
    "source_id": "doc-01",
    "raw_uri": "s3://rag-raw/default/doc-01/example.pdf",
    "output_dir": "storage/output/default/doc-01",
    "asset_count": 3,
    "asset_urls": [
      "http://localhost:9000/rag-assets/output/default/doc-01/images/fig1.png"
    ],
    "status": "succeeded",
    "job_id": "..."
  }

  If parsing or model initialization fails, the API should return a clear error and the ingest job should be marked failed with the error persisted in Postgres.

  You can inspect ingest jobs directly:

  docker compose exec postgres psql -U rag -d rag -c \
  "select tenant_id, source_id, status, error, updated_at from ingest_job order by updated_at desc;"

  Query RAG

  After at least one file has ingested successfully:

  curl -sS -X POST http://127.0.0.1:8080/query \
    -H "content-type: application/json" \
    -d '{
      "tenant_id": "default",
      "question": "What are the main themes across the uploaded documents?",
      "mode": "hybrid"
    }' | python3 -m json.tool

  For a source-specific question:

  curl -sS -X POST http://127.0.0.1:8080/query \
    -H "content-type: application/json" \
    -d '{
      "tenant_id": "default",
      "question": "Summarize the key facts from document doc-01.",
      "mode": "hybrid"
    }' | python3 -m json.tool

  The response shape is:

  {
    "answer": "...",
    "metadata": {
      "tenant_id": "default",
      "workspace": "...",
      "mode": "hybrid",
      "runtime": "raganything+lightrag"
    }
  }

  Generate llm-wiki Pages

  The llm-wiki is not a separate chat endpoint yet. It is a PostgreSQL-backed canonical wiki with pages, revisions, links, claims, sources, compile jobs, and validation results. The user-facing surface right now is
  the REST API.

  Compile a page from one source:

  curl -sS -X POST http://127.0.0.1:8080/wiki/compile \
    -H "content-type: application/json" \
    -d '{
      "tenant_id": "default",
      "source_id": "doc-01",
      "target_slug": "doc-01-summary"
    }' | python3 -m json.tool

  Compile a topic page across the indexed evidence:

  curl -sS -X POST http://127.0.0.1:8080/wiki/compile \
    -H "content-type: application/json" \
    -d '{
      "tenant_id": "default",
      "topic": "Main findings across the uploaded documents",
      "target_slug": "main-findings"
    }' | python -m json.tool

  The compiler creates deterministic Markdown pages with these sections:

  # Page Title

  ## Summary

  ...

  ## Key Concepts

  - ...

  ## Source-backed Claims

  - ...

  ## Related Pages

  - [[Related Page]]

  ## Open Questions

  - ...

  It also saves extracted claims to wiki_claim and source/provenance records to wiki_claim_source. If the current RAG metadata does not expose exact chunk/entity/relation IDs, the compiler preserves the raw metadata
  and source ID instead of fabricating citations.

  See What llm-wiki Looks Like

  Read a compiled page:

  curl -sS "http://127.0.0.1:8080/wiki/pages/doc-01-summary?tenant_id=default" \
    | python -m json.tool

  To see just the Markdown content:

  curl -sS "http://127.0.0.1:8080/wiki/pages/doc-01-summary?tenant_id=default" \
    | python -c 'import json,sys; print(json.load(sys.stdin)["current_revision"]["content"])'

  List backlinks for a wiki target:

  curl -sS "http://127.0.0.1:8080/wiki/pages/some-related-page/backlinks?tenant_id=default" \
    | python -m json.tool

  Validate a page:

  curl -sS -X POST \
    "http://127.0.0.1:8080/wiki/pages/doc-01-summary/validate?tenant_id=default" \
    | python -m json.tool

  Read validation results:

  curl -sS \
    "http://127.0.0.1:8080/wiki/pages/doc-01-summary/validation-results?tenant_id=default" \
    | python -m json.tool

  There is currently no HTML wiki UI and no list-pages endpoint. To see all pages, use SQL:

  docker compose exec postgres psql -U rag -d rag -c \
  "select slug, title, status, current_revision_id, updated_at from wiki_page where tenant_id = 'default' order by updated_at desc;"

  To inspect claims and provenance:

  docker compose exec postgres psql -U rag -d rag -c \
  "select p.slug, c.claim_text, c.support_status, c.confidence from wiki_claim c join wiki_page p on p.id = c.page_id where c.tenant_id = 'default' order by c.created_at desc limit 20;"

  docker compose exec postgres psql -U rag -d rag -c \
  "select source_id, document_uri, chunk_id, entity_id, relation_id, asset_url, quote from wiki_claim_source order by created_at desc limit 20;"

  What Is Still Missing Before This Feels Complete

  The main missing pieces for your exact workflow are:

  1. Real runtime smoke test with your LLM gateway.
  2. Confirmation that your embedding model dimension matches EMBEDDING_DIM.
  3. Confirmation that RAG-Anything parsing works for your file types with the selected PARSER=mineru and PARSE_METHOD=auto.
  4. A page listing/search endpoint for llm-wiki.
  5. A simple HTML/Markdown wiki viewer if you want to browse pages visually.
  6. A “query the wiki” endpoint if you mean semantic or full-text querying over wiki pages specifically, separate from querying the RAG index.
  7. Retry/dead-letter behavior for failed ingest jobs if you switch to async worker mode.

  For your immediate test, the shortest path is: fill .env, run uv sync --extra rag, start Postgres/MinIO, run migrations, start the API, upload one file first, query RAG, compile one wiki page, inspect the
  Markdown. Once that works, upload the remaining nine files.

  ---
  
  -- Connect to your PostgreSQL database (postgres:5432/rag)

-- 1. See what's stuck (inspect first)
SELECT *
FROM lightrag_doc_status
WHERE status != 'processed'
ORDER BY track_id;

-- 2. Delete all non-successful entries so re-ingest works
DELETE FROM lightrag_doc_status
WHERE status IS NULL
   OR status != 'processed';

-- 3. Also clean the failed doc_chunks references
DELETE FROM lightrag_doc_chunks
WHERE doc_id NOT IN (SELECT doc_name FROM lightrag_doc_status);

-- 4. Verify clean state
SELECT COUNT(*) AS remaining FROM lightrag_doc_status;
-- Should be 0 (or only truly processed entries)


docker-compose exec postgres psql -U rag -d rag -c "DROP SCHEMA ag_catalog CASCADE; CREATE SCHEMA ag_catalog; DROP SCHEMA ag_catalog public; CREATE SCHEMA public;"