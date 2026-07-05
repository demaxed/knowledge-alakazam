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
- Verification passed: `uv run ruff check .` and `uv run pytest`.
