from __future__ import annotations

from collections.abc import Iterable, Sequence
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from decimal import Decimal
from types import TracebackType
from typing import Any
from uuid import UUID, uuid4

import pytest
from wiki.models import WikiClaim, WikiClaimSource, WikiLink, WikiPage, WikiRevision
from wiki.repository import WikiBacklink
from wiki.service import (
    ClaimSourceInput,
    WikiService,
    extract_wikilinks,
)


class NoopTransaction(AbstractAsyncContextManager[None]):
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        return None


class InMemoryWikiRepository:
    def __init__(self) -> None:
        self.pages: dict[tuple[str, str], WikiPage] = {}
        self.revisions: dict[UUID, list[WikiRevision]] = {}
        self.links: list[WikiLink] = []
        self.claims: list[WikiClaim] = []
        self.claim_sources: list[WikiClaimSource] = []

    def transaction(self) -> AbstractAsyncContextManager[None]:
        return NoopTransaction()

    async def get_page_by_slug(self, tenant_id: str, slug: str) -> WikiPage | None:
        return self.pages.get((tenant_id, slug))

    async def create_page(
        self,
        *,
        tenant_id: str,
        slug: str,
        title: str,
        page_type: str = "concept",
        status: str = "draft",
    ) -> WikiPage:
        now = _now()
        page = WikiPage(
            id=uuid4(),
            tenant_id=tenant_id,
            slug=slug,
            title=title,
            page_type=page_type,
            status=status,
            current_revision_id=None,
            created_at=now,
            updated_at=now,
        )
        self.pages[(tenant_id, slug)] = page
        self.revisions[page.id] = []
        return page

    async def upsert_page_revision(
        self,
        *,
        page_id: UUID,
        content: str,
        revision_no: int | None = None,
        content_format: str = "markdown",
        content_json: dict[str, Any] | None = None,
        summary: str | None = None,
        author_type: str = "agent",
        set_current: bool = True,
    ) -> WikiRevision:
        page_revisions = self.revisions.setdefault(page_id, [])
        if revision_no is None:
            revision_no = len(page_revisions) + 1

        revision = next(
            (item for item in page_revisions if item.revision_no == revision_no),
            None,
        )
        if revision is None:
            revision = WikiRevision(
                id=uuid4(),
                page_id=page_id,
                revision_no=revision_no,
                content_format=content_format,
                content=content,
                content_json=content_json,
                summary=summary,
                author_type=author_type,
                created_at=_now(),
            )
            page_revisions.append(revision)
        else:
            revision.content_format = content_format
            revision.content = content
            revision.content_json = content_json
            revision.summary = summary
            revision.author_type = author_type

        if set_current:
            page = self._get_page_by_id(page_id)
            page.current_revision_id = revision.id
            page.updated_at = _now()

        return revision

    async def list_page_revisions(self, page_id: UUID) -> list[WikiRevision]:
        return sorted(self.revisions.get(page_id, []), key=lambda item: item.revision_no)

    async def get_current_revision(self, tenant_id: str, slug: str) -> WikiRevision | None:
        page = await self.get_page_by_slug(tenant_id, slug)
        if page is None or page.current_revision_id is None:
            return None

        for revision in self.revisions.get(page.id, []):
            if revision.id == page.current_revision_id:
                return revision
        return None

    async def replace_links_for_page(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        to_slugs: Sequence[str],
        link_type: str = "wikilink",
    ) -> list[WikiLink]:
        self.links = [
            link
            for link in self.links
            if not (link.tenant_id == tenant_id and link.from_page_id == page_id)
        ]

        created: list[WikiLink] = []
        for to_slug in _dedupe(to_slugs):
            link = WikiLink(
                id=uuid4(),
                tenant_id=tenant_id,
                from_page_id=page_id,
                to_slug=to_slug,
                link_type=link_type,
                created_at=_now(),
            )
            self.links.append(link)
            created.append(link)

        return created

    async def create_claim(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        revision_id: UUID,
        claim_text: str,
        support_status: str = "unknown",
        confidence: Decimal | None = None,
    ) -> WikiClaim:
        claim = WikiClaim(
            id=uuid4(),
            tenant_id=tenant_id,
            page_id=page_id,
            revision_id=revision_id,
            claim_text=claim_text,
            support_status=support_status,
            confidence=confidence,
            created_at=_now(),
        )
        self.claims.append(claim)
        return claim

    async def attach_claim_source(
        self,
        *,
        claim_id: UUID,
        source_id: str,
        document_uri: str | None = None,
        chunk_id: str | None = None,
        entity_id: str | None = None,
        relation_id: str | None = None,
        asset_url: str | None = None,
        page_no: int | None = None,
        bbox: dict[str, Any] | None = None,
        quote: str | None = None,
        locator: dict[str, Any] | None = None,
    ) -> WikiClaimSource:
        source = WikiClaimSource(
            id=uuid4(),
            claim_id=claim_id,
            source_id=source_id,
            document_uri=document_uri,
            chunk_id=chunk_id,
            entity_id=entity_id,
            relation_id=relation_id,
            asset_url=asset_url,
            page_no=page_no,
            bbox=bbox,
            quote=quote,
            locator=locator or {},
            created_at=_now(),
        )
        self.claim_sources.append(source)
        return source

    async def list_backlinks(self, tenant_id: str, slug: str) -> list[WikiBacklink]:
        backlinks: list[WikiBacklink] = []
        for link in self.links:
            if link.tenant_id != tenant_id or link.to_slug != slug:
                continue

            page = self._get_page_by_id(link.from_page_id)
            backlinks.append(WikiBacklink(link=link, page=page))

        return sorted(backlinks, key=lambda item: (item.page.title, item.page.slug))

    def _get_page_by_id(self, page_id: UUID) -> WikiPage:
        for page in self.pages.values():
            if page.id == page_id:
                return page
        raise AssertionError(f"Missing page {page_id}")


@pytest.mark.asyncio
async def test_create_or_update_page_creates_page_and_revision() -> None:
    service = WikiService(InMemoryWikiRepository())

    detail = await service.create_or_update_page(
        tenant_id="tenant-a",
        title="Some Page",
        content="Initial content",
    )

    assert detail.page.slug == "some-page"
    assert detail.page.title == "Some Page"
    assert detail.current_revision is not None
    assert detail.current_revision.revision_no == 1
    assert detail.current_revision.content == "Initial content"
    assert detail.page.current_revision_id == detail.current_revision.id


@pytest.mark.asyncio
async def test_create_revision_increments_revision_number() -> None:
    repository = InMemoryWikiRepository()
    service = WikiService(repository)
    await service.create_or_update_page(
        tenant_id="tenant-a",
        title="Some Page",
        content="Initial content",
    )

    detail = await service.create_revision(
        tenant_id="tenant-a",
        slug="some-page",
        content="Second revision",
    )

    assert detail.current_revision is not None
    assert detail.current_revision.revision_no == 2
    assert detail.current_revision.content == "Second revision"
    assert [
        revision.revision_no
        for revision in await repository.list_page_revisions(detail.page.id)
    ] == [1, 2]


def test_extract_wikilinks_slugifies_and_deduplicates_targets() -> None:
    markdown = (
        "See [[Some Page]], [[Another Page|label]], [[Some Page]], "
        "[[#Section Only]], and [[Third_Page]]."
    )

    assert extract_wikilinks(markdown) == ["some-page", "another-page", "third-page"]


@pytest.mark.asyncio
async def test_backlinks_are_rebuilt_from_markdown() -> None:
    repository = InMemoryWikiRepository()
    service = WikiService(repository)
    await service.create_or_update_page(
        tenant_id="tenant-a",
        title="Target Page",
        content="Target content",
    )
    await service.create_or_update_page(
        tenant_id="tenant-a",
        title="Source Page",
        content="See [[Target Page]].",
    )

    backlinks = await service.get_backlinks(tenant_id="tenant-a", slug="target-page")

    assert [backlink.page.slug for backlink in backlinks] == ["source-page"]
    await service.rebuild_links_from_markdown(
        tenant_id="tenant-a",
        slug="source-page",
        markdown="No links now.",
    )
    assert await service.get_backlinks(tenant_id="tenant-a", slug="target-page") == []


@pytest.mark.asyncio
async def test_add_claim_with_sources_uses_current_revision() -> None:
    repository = InMemoryWikiRepository()
    service = WikiService(repository)
    detail = await service.create_or_update_page(
        tenant_id="tenant-a",
        title="Claim Page",
        content="Claim content",
    )

    bundle = await service.add_claim_with_sources(
        tenant_id="tenant-a",
        slug="claim-page",
        claim_text="The claim is supported.",
        sources=[ClaimSourceInput(source_id="source-1", quote="quoted text")],
        confidence=Decimal("0.9000"),
    )

    assert detail.current_revision is not None
    assert bundle.claim.revision_id == detail.current_revision.id
    assert bundle.sources[0].claim_id == bundle.claim.id
    assert bundle.sources[0].source_id == "source-1"


def _now() -> datetime:
    return datetime.now(UTC)


def _dedupe(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
