# Task 2: App Configuration and Database Layer

Implement the configuration and async database layer.

Add:

1. `app/config.py`

   * `Settings` based on `pydantic-settings`
   * env variables:

     * `ENV`
     * `SERVICE_NAME`
     * `APP_DATABASE_URL`
     * `RAG_WORKING_DIR`
     * `RAG_OUTPUT_DIR`
     * `RAG_INPUT_DIR`
     * `PARSER`
     * `PARSE_METHOD`
     * `OPENAI_API_KEY`
     * `OPENAI_BASE_URL`
     * `LLM_MODEL`
     * `VISION_MODEL`
     * `EMBEDDING_MODEL`
     * `EMBEDDING_DIM`
     * S3/MinIO settings
     * LightRAG storage settings

2. `app/db.py`

   * async engine
   * async sessionmaker
   * dependency `get_db_session`
   * lifespan init/dispose

3. Update `app/main.py`

   * FastAPI lifespan
   * include routers
   * health router

4. Tests:

   * config loads from environment
   * database URL parsing does not break
   * health endpoint still works

Acceptance criteria:

* Settings do not hardcode secrets.
* `.env.example` contains all variables.
* `uv run ruff check .` passes.
* `uv run pytest` passes.