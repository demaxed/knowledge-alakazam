# Task 9: llm-wiki Compiler Skeleton

Implement a `WikiCompiler` skeleton that builds wiki pages on top of RAG evidence.

Add `wiki/compiler.py`.

Scope of the first version:

1. `WikiCompiler` class:

   * `compile_source_to_pages(tenant_id, source_id)`
   * `compile_topic_page(tenant_id, topic, evidence_query)`
   * `update_existing_page_with_evidence(tenant_id, slug, evidence)`

2. It must use the RAG runtime to search evidence:

   * query LightRAG/RAG-Anything
   * default mode: `hybrid`

3. It must create/update wiki pages through `WikiService`.

4. Page format:

   * Markdown
   * sections:

     * Summary
     * Key Concepts
     * Source-backed Claims
     * Related Pages
     * Open Questions
   * wikilinks through `[[...]]`

5. Provenance:

   * claims should be saved to `wiki_claim`
   * sources should be saved to `wiki_claim_source`
   * if exact chunk/entity IDs are unavailable from the current RAG API, save the best available locator metadata and document/source ID

6. Add compile job table usage:

   * create pending job
   * mark processing/succeeded/failed

7. API endpoint:

   * `POST /wiki/compile`
   * params:

     * `tenant_id`
     * `source_id`, optional
     * `topic`, optional
     * `target_slug`, optional

Acceptance criteria:

* Compiler is deterministic where possible.
* No fake citations.
* If evidence lacks structured source IDs, preserve raw metadata and document the limitation in README.
* `uv run ruff check .` passes.
* `uv run pytest` passes.