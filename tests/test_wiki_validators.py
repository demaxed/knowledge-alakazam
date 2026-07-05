from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from app.api.wiki import get_wiki_validation_service
from app.config import Settings
from app.main import create_app
from fastapi.testclient import TestClient
from wiki.service import ClaimSourceInput, WikiService
from wiki.validators import (
    BrokenWikilinksValidator,
    DuplicateSlugTitleValidator,
    StalePageValidator,
    UnsupportedClaimsValidator,
    WikiValidationService,
)

from tests.test_wiki_service import InMemoryWikiRepository


@pytest.mark.asyncio
async def test_validation_detects_broken_links_claims_and_duplicate_titles() -> None:
    repository = InMemoryWikiRepository()
    wiki_service = WikiService(repository)
    validation_service = WikiValidationService(
        repository,
        validators=(
            BrokenWikilinksValidator(),
            UnsupportedClaimsValidator(),
            DuplicateSlugTitleValidator(),
        ),
    )
    await wiki_service.create_or_update_page(
        tenant_id="tenant-a",
        title="Existing Target",
        content="Target content",
    )
    await wiki_service.create_or_update_page(
        tenant_id="tenant-a",
        title="Source Page",
        slug="source-copy",
        content="Duplicate title page",
    )
    await wiki_service.create_or_update_page(
        tenant_id="tenant-a",
        title="Source Page",
        slug="source-page",
        content="See [[Existing Target]] and [[Missing Target]].",
    )
    await wiki_service.add_claim_with_sources(
        tenant_id="tenant-a",
        slug="source-page",
        claim_text="This claim still needs support.",
        sources=[ClaimSourceInput(source_id="source-1")],
    )

    run = await validation_service.validate_page(tenant_id="tenant-a", slug="source-page")

    assert run.revision.content.startswith("See")
    assert [result.validator_name for result in run.results] == [
        "broken_wikilinks",
        "unsupported_claims",
        "duplicate_slug_title",
    ]
    assert run.results[0].severity == "error"
    assert run.results[0].metadata_ == {"target_slug": "missing-target"}
    assert run.results[1].severity == "warning"
    assert run.results[1].metadata_["support_status"] == "unknown"
    assert run.results[2].severity == "warning"
    assert run.results[2].metadata_ == {
        "title": "Source Page",
        "matching_slugs": ["source-copy"],
    }

    listed = await validation_service.list_page_results(tenant_id="tenant-a", slug="source-page")
    assert [result.id for result in listed.results] == [result.id for result in run.results]


@pytest.mark.asyncio
async def test_validation_replaces_previous_results() -> None:
    repository = InMemoryWikiRepository()
    wiki_service = WikiService(repository)
    validation_service = WikiValidationService(
        repository,
        validators=(BrokenWikilinksValidator(),),
    )
    await wiki_service.create_or_update_page(
        tenant_id="tenant-a",
        title="Source Page",
        content="See [[Missing Target]].",
    )

    first_run = await validation_service.validate_page(tenant_id="tenant-a", slug="source-page")
    assert len(first_run.results) == 1

    await wiki_service.create_revision(
        tenant_id="tenant-a",
        slug="source-page",
        content="No links now.",
    )
    second_run = await validation_service.validate_page(tenant_id="tenant-a", slug="source-page")

    assert second_run.results == []
    current_results = await validation_service.list_page_results(
        tenant_id="tenant-a",
        slug="source-page",
    )
    assert current_results.results == []


@pytest.mark.asyncio
async def test_stale_page_validator_skeleton_flags_old_pages() -> None:
    repository = InMemoryWikiRepository()
    wiki_service = WikiService(repository)
    validation_service = WikiValidationService(
        repository,
        validators=(StalePageValidator(stale_after_days=30),),
    )
    detail = await wiki_service.create_or_update_page(
        tenant_id="tenant-a",
        title="Old Page",
        content="Still current, but old.",
    )
    detail.page.updated_at = datetime.now(UTC) - timedelta(days=45)

    run = await validation_service.validate_page(tenant_id="tenant-a", slug="old-page")

    assert len(run.results) == 1
    assert run.results[0].validator_name == "stale_page"
    assert run.results[0].severity == "info"
    assert run.results[0].metadata_["stale_after_days"] == 30


def test_validation_endpoints_run_and_list_results() -> None:
    settings = Settings(app_database_url="postgresql+asyncpg://rag:rag@localhost:5432/rag")
    repository = InMemoryWikiRepository()
    wiki_service = WikiService(repository)
    validation_service = WikiValidationService(
        repository,
        validators=(BrokenWikilinksValidator(),),
    )

    async def setup_pages() -> None:
        await wiki_service.create_or_update_page(
            tenant_id="tenant-a",
            title="Source Page",
            content="See [[Missing Target]].",
        )

    asyncio.run(setup_pages())

    application = create_app(settings)
    application.dependency_overrides[get_wiki_validation_service] = lambda: validation_service

    with TestClient(application) as client:
        validate_response = client.post(
            "/wiki/pages/source-page/validate",
            params={"tenant_id": "tenant-a"},
        )
        list_response = client.get(
            "/wiki/pages/source-page/validation-results",
            params={"tenant_id": "tenant-a"},
        )

    assert validate_response.status_code == 200
    validate_payload = validate_response.json()
    assert validate_payload["tenant_id"] == "tenant-a"
    assert validate_payload["slug"] == "source-page"
    assert validate_payload["result_count"] == 1
    assert validate_payload["results"][0]["validator_name"] == "broken_wikilinks"
    assert validate_payload["results"][0]["metadata"] == {"target_slug": "missing-target"}

    assert list_response.status_code == 200
    assert list_response.json()["results"] == validate_payload["results"]
