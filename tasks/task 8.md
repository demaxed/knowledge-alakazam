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