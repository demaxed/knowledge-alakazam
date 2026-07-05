# Task 4: WikiRepository and WikiService

Implement the repository/service layer for llm-wiki.

Add:

1. `wiki/repository.py`

   * `get_page_by_slug(tenant_id, slug)`
   * `create_page(...)`
   * `upsert_page_revision(...)`
   * `list_page_revisions(page_id)`
   * `get_current_revision(tenant_id, slug)`
   * `create_links_for_revision(...)`
   * `replace_links_for_page(...)`
   * `create_claim(...)`
   * `attach_claim_source(...)`
   * `list_backlinks(tenant_id, slug)`

2. `wiki/service.py`

   * higher-level methods:

     * `create_or_update_page`
     * `publish_page`
     * `get_page`
     * `add_claim_with_sources`
     * `rebuild_links_from_markdown`

3. Markdown wikilink parser:

   * find `[[Some Page]]`
   * slugify target
   * save links

4. API endpoints in `app/api/wiki.py`:

   * `POST /wiki/pages`
   * `GET /wiki/pages/{slug}`
   * `POST /wiki/pages/{slug}/revisions`
   * `GET /wiki/pages/{slug}/backlinks`

5. Pydantic schemas in `app/schemas.py`.

Acceptance criteria:

* Repository methods are async.
* Transactions are explicit and safe.
* Tests cover:

  * page creation
  * revision increment
  * wikilink extraction
  * backlinks
* `uv run ruff check .` passes.
* `uv run pytest` passes.