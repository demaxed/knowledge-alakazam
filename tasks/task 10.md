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