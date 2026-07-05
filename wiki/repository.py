from __future__ import annotations

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wiki.models import (
    WikiClaim,
    WikiClaimSource,
    WikiLink,
    WikiPage,
    WikiRevision,
)


@dataclass(frozen=True, slots=True)
class WikiBacklink:
    link: WikiLink
    page: WikiPage


def _dedupe_slugs(to_slugs: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []

    for slug in to_slugs:
        if slug in seen:
            continue
        seen.add(slug)
        deduped.append(slug)

    return deduped


class WikiRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[None]:
        if self.session.in_transaction():
            yield
            return

        async with self.session.begin():
            yield

    async def get_page_by_slug(self, tenant_id: str, slug: str) -> WikiPage | None:
        result = await self.session.scalars(
            select(WikiPage).where(
                WikiPage.tenant_id == tenant_id,
                WikiPage.slug == slug,
            )
        )
        return result.one_or_none()

    async def create_page(
        self,
        *,
        tenant_id: str,
        slug: str,
        title: str,
        page_type: str = "concept",
        status: str = "draft",
    ) -> WikiPage:
        page = WikiPage(
            tenant_id=tenant_id,
            slug=slug,
            title=title,
            page_type=page_type,
            status=status,
        )
        self.session.add(page)
        await self.session.flush()
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
        if revision_no is None:
            revision_no = await self._next_revision_no(page_id)

        revision = await self._get_revision_by_no(page_id, revision_no)
        if revision is None:
            revision = WikiRevision(
                page_id=page_id,
                revision_no=revision_no,
                content_format=content_format,
                content=content,
                content_json=content_json,
                summary=summary,
                author_type=author_type,
            )
            self.session.add(revision)
        else:
            revision.content_format = content_format
            revision.content = content
            revision.content_json = content_json
            revision.summary = summary
            revision.author_type = author_type

        await self.session.flush()

        if set_current:
            page = await self.session.get(WikiPage, page_id)
            if page is None:
                raise ValueError(f"Wiki page {page_id} does not exist")
            page.current_revision_id = revision.id
            await self.session.flush()

        return revision

    async def list_page_revisions(self, page_id: UUID) -> list[WikiRevision]:
        result = await self.session.scalars(
            select(WikiRevision)
            .where(WikiRevision.page_id == page_id)
            .order_by(WikiRevision.revision_no)
        )
        return list(result.all())

    async def get_current_revision(self, tenant_id: str, slug: str) -> WikiRevision | None:
        result = await self.session.scalars(
            select(WikiRevision)
            .join(WikiPage, WikiPage.current_revision_id == WikiRevision.id)
            .where(
                WikiPage.tenant_id == tenant_id,
                WikiPage.slug == slug,
            )
        )
        return result.one_or_none()

    async def create_links_for_revision(
        self,
        *,
        tenant_id: str,
        revision_id: UUID,
        to_slugs: Iterable[str],
        link_type: str = "wikilink",
    ) -> list[WikiLink]:
        revision = await self.session.get(WikiRevision, revision_id)
        if revision is None:
            raise ValueError(f"Wiki revision {revision_id} does not exist")

        return await self._create_links_for_page(
            tenant_id=tenant_id,
            page_id=revision.page_id,
            to_slugs=to_slugs,
            link_type=link_type,
        )

    async def replace_links_for_page(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        to_slugs: Iterable[str],
        link_type: str = "wikilink",
    ) -> list[WikiLink]:
        await self.session.execute(
            delete(WikiLink).where(
                WikiLink.tenant_id == tenant_id,
                WikiLink.from_page_id == page_id,
            )
        )
        return await self._create_links_for_page(
            tenant_id=tenant_id,
            page_id=page_id,
            to_slugs=to_slugs,
            link_type=link_type,
        )

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
            tenant_id=tenant_id,
            page_id=page_id,
            revision_id=revision_id,
            claim_text=claim_text,
            support_status=support_status,
            confidence=confidence,
        )
        self.session.add(claim)
        await self.session.flush()
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
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def list_backlinks(self, tenant_id: str, slug: str) -> list[WikiBacklink]:
        result = await self.session.execute(
            select(WikiLink, WikiPage)
            .join(WikiPage, WikiPage.id == WikiLink.from_page_id)
            .where(
                WikiLink.tenant_id == tenant_id,
                WikiPage.tenant_id == tenant_id,
                WikiLink.to_slug == slug,
            )
            .order_by(WikiPage.title, WikiPage.slug)
        )
        return [WikiBacklink(link=link, page=page) for link, page in result.all()]

    async def _create_links_for_page(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        to_slugs: Iterable[str],
        link_type: str,
    ) -> list[WikiLink]:
        links = [
            WikiLink(
                tenant_id=tenant_id,
                from_page_id=page_id,
                to_slug=to_slug,
                link_type=link_type,
            )
            for to_slug in _dedupe_slugs(to_slugs)
        ]
        self.session.add_all(links)
        await self.session.flush()
        return links

    async def _next_revision_no(self, page_id: UUID) -> int:
        result = await self.session.scalar(
            select(func.coalesce(func.max(WikiRevision.revision_no), 0)).where(
                WikiRevision.page_id == page_id
            )
        )
        return int(result or 0) + 1

    async def _get_revision_by_no(
        self,
        page_id: UUID,
        revision_no: int,
    ) -> WikiRevision | None:
        result = await self.session.scalars(
            select(WikiRevision).where(
                WikiRevision.page_id == page_id,
                WikiRevision.revision_no == revision_no,
            )
        )
        return result.one_or_none()
