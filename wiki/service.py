from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from wiki.models import WikiClaim, WikiClaimSource, WikiLink, WikiPage, WikiRevision
from wiki.repository import WikiBacklink

WIKILINK_PATTERN = re.compile(r"\[\[([^\[\]\n]+)\]\]")


class WikiPageNotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ClaimSourceInput:
    source_id: str
    document_uri: str | None = None
    chunk_id: str | None = None
    entity_id: str | None = None
    relation_id: str | None = None
    asset_url: str | None = None
    page_no: int | None = None
    bbox: dict[str, Any] | None = None
    quote: str | None = None
    locator: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class WikiPageDetail:
    page: WikiPage
    current_revision: WikiRevision | None


@dataclass(frozen=True, slots=True)
class WikiClaimBundle:
    claim: WikiClaim
    sources: list[WikiClaimSource]


class WikiRepositoryProtocol(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[None]:
        pass

    async def get_page_by_slug(self, tenant_id: str, slug: str) -> WikiPage | None:
        pass

    async def create_page(
        self,
        *,
        tenant_id: str,
        slug: str,
        title: str,
        page_type: str = "concept",
        status: str = "draft",
    ) -> WikiPage:
        pass

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
        pass

    async def list_page_revisions(self, page_id: UUID) -> list[WikiRevision]:
        pass

    async def get_current_revision(self, tenant_id: str, slug: str) -> WikiRevision | None:
        pass

    async def replace_links_for_page(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        to_slugs: Sequence[str],
        link_type: str = "wikilink",
    ) -> list[WikiLink]:
        pass

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
        pass

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
        pass

    async def list_backlinks(self, tenant_id: str, slug: str) -> list[WikiBacklink]:
        pass


def slugify_wiki_target(value: str) -> str:
    page_part = value.split("|", maxsplit=1)[0].split("#", maxsplit=1)[0]
    normalized = unicodedata.normalize("NFKC", page_part).strip().lower()
    normalized = re.sub(r"[^\w\s-]", "", normalized, flags=re.UNICODE)
    normalized = re.sub(r"[\s_-]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-")


def extract_wikilinks(markdown: str) -> list[str]:
    slugs: list[str] = []
    seen: set[str] = set()

    for match in WIKILINK_PATTERN.finditer(markdown):
        slug = slugify_wiki_target(match.group(1))
        if not slug or slug in seen:
            continue
        seen.add(slug)
        slugs.append(slug)

    return slugs


class WikiService:
    def __init__(self, repository: WikiRepositoryProtocol) -> None:
        self.repository = repository

    async def create_or_update_page(
        self,
        *,
        tenant_id: str,
        title: str,
        content: str,
        slug: str | None = None,
        page_type: str = "concept",
        status: str | None = None,
        content_format: str = "markdown",
        content_json: dict[str, Any] | None = None,
        summary: str | None = None,
        author_type: str = "agent",
    ) -> WikiPageDetail:
        resolved_slug = _require_slug(slug or title)

        async with self.repository.transaction():
            page = await self.repository.get_page_by_slug(tenant_id, resolved_slug)
            if page is None:
                page = await self.repository.create_page(
                    tenant_id=tenant_id,
                    slug=resolved_slug,
                    title=title,
                    page_type=page_type,
                    status=status or "draft",
                )
            else:
                page.title = title
                page.page_type = page_type
                if status is not None:
                    page.status = status

            revision = await self.repository.upsert_page_revision(
                page_id=page.id,
                content=content,
                content_format=content_format,
                content_json=content_json,
                summary=summary,
                author_type=author_type,
            )
            await self._replace_links_for_content(
                tenant_id=tenant_id,
                page_id=page.id,
                content=content,
                content_format=content_format,
            )
            return WikiPageDetail(page=page, current_revision=revision)

    async def publish_page(
        self,
        *,
        tenant_id: str,
        slug: str,
        revision_no: int | None = None,
    ) -> WikiPageDetail:
        resolved_slug = _require_slug(slug)

        async with self.repository.transaction():
            page = await self._require_page(tenant_id, resolved_slug)
            revision = await self._resolve_revision(page, tenant_id, resolved_slug, revision_no)
            page.current_revision_id = revision.id
            page.status = "published"
            return WikiPageDetail(page=page, current_revision=revision)

    async def get_page(self, *, tenant_id: str, slug: str) -> WikiPageDetail:
        resolved_slug = _require_slug(slug)
        page = await self._require_page(tenant_id, resolved_slug)
        revision = await self.repository.get_current_revision(tenant_id, resolved_slug)
        return WikiPageDetail(page=page, current_revision=revision)

    async def create_revision(
        self,
        *,
        tenant_id: str,
        slug: str,
        content: str,
        content_format: str = "markdown",
        content_json: dict[str, Any] | None = None,
        summary: str | None = None,
        author_type: str = "agent",
    ) -> WikiPageDetail:
        resolved_slug = _require_slug(slug)

        async with self.repository.transaction():
            page = await self._require_page(tenant_id, resolved_slug)
            revision = await self.repository.upsert_page_revision(
                page_id=page.id,
                content=content,
                content_format=content_format,
                content_json=content_json,
                summary=summary,
                author_type=author_type,
            )
            await self._replace_links_for_content(
                tenant_id=tenant_id,
                page_id=page.id,
                content=content,
                content_format=content_format,
            )
            return WikiPageDetail(page=page, current_revision=revision)

    async def add_claim_with_sources(
        self,
        *,
        tenant_id: str,
        slug: str,
        claim_text: str,
        sources: Sequence[ClaimSourceInput],
        support_status: str = "unknown",
        confidence: Decimal | None = None,
    ) -> WikiClaimBundle:
        resolved_slug = _require_slug(slug)

        async with self.repository.transaction():
            page = await self._require_page(tenant_id, resolved_slug)
            revision = await self.repository.get_current_revision(tenant_id, resolved_slug)
            if revision is None:
                raise ValueError(f"Wiki page '{resolved_slug}' has no current revision")

            claim = await self.repository.create_claim(
                tenant_id=tenant_id,
                page_id=page.id,
                revision_id=revision.id,
                claim_text=claim_text,
                support_status=support_status,
                confidence=confidence,
            )
            attached_sources = [
                await self.repository.attach_claim_source(
                    claim_id=claim.id,
                    source_id=source.source_id,
                    document_uri=source.document_uri,
                    chunk_id=source.chunk_id,
                    entity_id=source.entity_id,
                    relation_id=source.relation_id,
                    asset_url=source.asset_url,
                    page_no=source.page_no,
                    bbox=source.bbox,
                    quote=source.quote,
                    locator=source.locator,
                )
                for source in sources
            ]
            return WikiClaimBundle(claim=claim, sources=attached_sources)

    async def rebuild_links_from_markdown(
        self,
        *,
        tenant_id: str,
        slug: str,
        markdown: str,
    ) -> list[WikiLink]:
        resolved_slug = _require_slug(slug)

        async with self.repository.transaction():
            page = await self._require_page(tenant_id, resolved_slug)
            return await self.repository.replace_links_for_page(
                tenant_id=tenant_id,
                page_id=page.id,
                to_slugs=extract_wikilinks(markdown),
            )

    async def get_backlinks(self, *, tenant_id: str, slug: str) -> list[WikiBacklink]:
        return await self.repository.list_backlinks(tenant_id, _require_slug(slug))

    async def _require_page(self, tenant_id: str, slug: str) -> WikiPage:
        page = await self.repository.get_page_by_slug(tenant_id, slug)
        if page is None:
            raise WikiPageNotFoundError(f"Wiki page '{slug}' was not found")
        return page

    async def _resolve_revision(
        self,
        page: WikiPage,
        tenant_id: str,
        slug: str,
        revision_no: int | None,
    ) -> WikiRevision:
        if revision_no is None:
            revision = await self.repository.get_current_revision(tenant_id, slug)
            if revision is None:
                raise ValueError(f"Wiki page '{slug}' has no current revision")
            return revision

        revisions = await self.repository.list_page_revisions(page.id)
        for revision in revisions:
            if revision.revision_no == revision_no:
                return revision

        raise ValueError(f"Wiki page '{slug}' has no revision {revision_no}")

    async def _replace_links_for_content(
        self,
        *,
        tenant_id: str,
        page_id: UUID,
        content: str,
        content_format: str,
    ) -> None:
        await self.repository.replace_links_for_page(
            tenant_id=tenant_id,
            page_id=page_id,
            to_slugs=extract_wikilinks(content) if content_format == "markdown" else [],
        )


def _require_slug(value: str) -> str:
    slug = slugify_wiki_target(value)
    if not slug:
        raise ValueError("Wiki page slug cannot be empty")
    return slug
