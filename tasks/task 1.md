# Task 1: Docker Compose Production-Like Environment

Implement the Docker Compose environment for production-like local development.

Add:

1. `docker-compose.yml` with services:

   * `postgres`
   * `minio`
   * `create-buckets`
   * `app`

2. PostgreSQL:

   * use an image with `pgvector` and `Apache AGE`
   * database: `rag`
   * user: `rag`
   * password through env/example
   * healthcheck with `pg_isready`
   * persistent data volume
   * init SQL from `db/init/001_extensions.sql`

3. MinIO:

   * S3-compatible endpoint
   * console port
   * buckets:

     * `rag-raw`
     * `rag-assets`

4. App:

   * build from `Dockerfile`
   * depends on PostgreSQL healthcheck and bucket creation
   * expose port `8080:8080`
   * use `.env.example` as `env_file`
   * volumes:

     * `/data/rag_storage`
     * `/data/output`
     * `/data/inputs`

5. `Dockerfile`:

   * Python 3.11 slim
   * install `uv`
   * install system dependencies for document parsing:

     * libreoffice
     * poppler-utils
     * tesseract-ocr
     * curl
     * build-essential if needed
   * install app dependencies via `uv sync`
   * run `uvicorn app.main:app`

6. `db/init/001_extensions.sql`:

   * `CREATE EXTENSION IF NOT EXISTS vector;`
   * `CREATE EXTENSION IF NOT EXISTS age;`
   * safe `search_path` setup if required

7. Update README:

   * how to run `docker compose up --build`
   * how to open the MinIO console
   * how to check `/health`
   * which env variables are important

Acceptance criteria:

* `docker compose config` passes.
* `docker compose up --build` starts app, postgres, and minio.
* `/health` returns OK.
* README describes the startup flow.
* `uv run ruff check .` passes.
* `uv run pytest` passes.
