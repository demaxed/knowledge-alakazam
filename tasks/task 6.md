# Task 6: LightRAG + RAG-Anything Runtime

Implement the runtime integration layer.

Add `app/rag_runtime.py`.

Requirements:

1. Create `RAGRuntime` class:

   * owns the LightRAG instance
   * owns the RAGAnything instance
   * supports async initialization
   * supports graceful shutdown if the package API supports it

2. LightRAG:

   * `working_dir` from settings
   * configurable LLM model function
   * configurable embedding function
   * storage backends through env
   * call `initialize_storages()`
   * call pipeline status initialization if required by the actual package API

3. RAG-Anything:

   * pass an existing LightRAG instance
   * configure vision model function
   * support image/table/equation processing flags if the actual package API supports them

4. LLM providers:

   * implement OpenAI-compatible default
   * use env:

     * `OPENAI_API_KEY`
     * `OPENAI_BASE_URL`
     * `LLM_MODEL`
     * `VISION_MODEL`
     * `EMBEDDING_MODEL`
     * `EMBEDDING_DIM`
   * keep the code isolated so another provider can be added later

5. Important:

   * do not invent imports
   * inspect the installed package API if needed
   * if the RAG-Anything/LightRAG API differs, adapt and document it in README

6. Add endpoint:

   * `POST /query`
   * body:

     * `tenant_id`
     * `question`
     * `mode`, default `hybrid`
     * `vlm_enhanced`, optional
   * returns answer and metadata

Acceptance criteria:

* App starts without initializing LLM if env says `RAG_RUNTIME_DISABLED=true` for tests/local.
* Runtime initialization is lazy or guarded for tests.
* Query endpoint returns a graceful error if runtime is disabled.
* `uv run ruff check .` passes.
* `uv run pytest` passes.
