# Task 3: Alembic Migrations for llm-wiki Canonical Store

Implement the PostgreSQL schema for the llm-wiki canonical store.

Add Alembic and migrations for the following tables:

1. `wiki_page`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `slug TEXT NOT NULL`
   * `title TEXT NOT NULL`
   * `page_type TEXT NOT NULL DEFAULT 'concept'`
   * `status TEXT NOT NULL DEFAULT 'draft'`
   * `current_revision_id UUID NULL`
   * timestamps
   * unique `(tenant_id, slug)`

2. `wiki_revision`

   * `id UUID PK`
   * `page_id UUID FK`
   * `revision_no INT NOT NULL`
   * `content_format TEXT NOT NULL DEFAULT 'markdown'`
   * `content TEXT NOT NULL`
   * `content_json JSONB NULL`
   * `summary TEXT NULL`
   * `author_type TEXT NOT NULL DEFAULT 'agent'`
   * timestamp
   * unique `(page_id, revision_no)`

3. `wiki_link`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `from_page_id UUID FK`
   * `to_slug TEXT NOT NULL`
   * `link_type TEXT NOT NULL DEFAULT 'wikilink'`
   * timestamp
   * indexes for backlinks

4. `wiki_claim`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `page_id UUID FK`
   * `revision_id UUID FK`
   * `claim_text TEXT NOT NULL`
   * `support_status TEXT NOT NULL DEFAULT 'unknown'`
   * `confidence NUMERIC(5, 4) NULL`
   * timestamp

5. `wiki_claim_source`

   * `id UUID PK`
   * `claim_id UUID FK`
   * `source_id TEXT NOT NULL`
   * `document_uri TEXT NULL`
   * `chunk_id TEXT NULL`
   * `entity_id TEXT NULL`
   * `relation_id TEXT NULL`
   * `asset_url TEXT NULL`
   * `page_no INT NULL`
   * `bbox JSONB NULL`
   * `quote TEXT NULL`
   * `locator JSONB NOT NULL DEFAULT '{}'`
   * timestamp

6. `ingest_job`

   * `id UUID PK`
   * `tenant_id TEXT NOT NULL`
   * `source_id TEXT NOT NULL`
   * raw bucket/key
   * enum-like status check:

     * pending
     * processing
     * succeeded
     * failed
   * error text
   * timestamps
   * unique `(tenant_id, source_id)`

7. `wiki_compile_job`

   * `id UUID PK`
   * `tenant_id`
   * `source_id`
   * `target_slug NULL`
   * status
   * error
   * timestamps

8. `wiki_validation_result`

   * `id UUID PK`
   * `tenant_id`
   * `page_id`
   * `revision_id`
   * `validator_name`
   * `severity`
   * `message`
   * `metadata JSONB`
   * timestamp

Also:

* Create SQLAlchemy models in `wiki/models.py`.
* Configure Alembic env for async SQLAlchemy metadata.
* Add README commands:

  * `uv run alembic upgrade head`
  * `uv run alembic revision --autogenerate -m "..."`
* Add model/repository tests where possible without a real PostgreSQL instance.
* If real PostgreSQL is required, mark the tests as integration tests.

Acceptance criteria:

* Alembic migration is generated and applicable.
* Models match the migration.
* `uv run ruff check .` passes.
* `uv run pytest` passes.