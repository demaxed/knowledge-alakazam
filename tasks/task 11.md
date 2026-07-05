# Task 11: Final Hardening and Docs

Perform the final production-hardening pass.

Requirements:

1. README:

   * architecture overview
   * local run with uv
   * local run with Docker Compose
   * migrations
   * ingest example with curl
   * query example with curl
   * wiki page example
   * worker usage
   * env variables table
   * known limitations

2. Add `docs/architecture.md`:

   * components
   * data flow
   * storage model
   * ingest lifecycle
   * wiki compiler lifecycle
   * S3 asset strategy
   * PostgreSQL schema explanation

3. Add `docs/operations.md`:

   * backup considerations
   * embedding dimension immutability
   * PostgreSQL extensions
   * object storage lifecycle
   * how to reindex
   * how to replay wiki compile jobs

4. Add Makefile or task commands if useful:

   * `make test`
   * `make lint`
   * `make format`
   * `make migrate`
   * but keep uv as the primary tool

5. Run:

   * `uv run ruff format .`
   * `uv run ruff check .`
   * `uv run pytest`

6. Fix all issues.

Acceptance criteria:

* Project is understandable from README.
* Docker Compose can start the local stack.
* Tests pass.
* No secrets are committed.
* Known limitations are explicit.
