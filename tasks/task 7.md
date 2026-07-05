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