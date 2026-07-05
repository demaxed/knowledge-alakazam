from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from wiki.models import WikiRevision
from wiki.repository import WikiBacklink, WikiRepository
from wiki.service import WikiPageDetail, WikiPageNotFoundError, WikiService

from app.db import get_db_session
from app.schemas import (
    WikiBacklinkResponse,
    WikiPageCreateRequest,
    WikiPageResponse,
    WikiRevisionCreateRequest,
    WikiRevisionResponse,
)

router = APIRouter(prefix="/wiki", tags=["wiki"])


async def get_wiki_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WikiService:
    return WikiService(WikiRepository(session))


@router.post(
    "/pages",
    response_model=WikiPageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_page(
    payload: WikiPageCreateRequest,
    service: Annotated[WikiService, Depends(get_wiki_service)],
) -> WikiPageResponse:
    try:
        detail = await service.create_or_update_page(
            tenant_id=payload.tenant_id,
            title=payload.title,
            slug=payload.slug,
            page_type=payload.page_type,
            status=payload.status,
            content=payload.content,
            content_format=payload.content_format,
            content_json=payload.content_json,
            summary=payload.summary,
            author_type=payload.author_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _page_response(detail)


@router.get("/pages/{slug}", response_model=WikiPageResponse)
async def get_page(
    slug: str,
    tenant_id: Annotated[str, Query(min_length=1)],
    service: Annotated[WikiService, Depends(get_wiki_service)],
) -> WikiPageResponse:
    try:
        detail = await service.get_page(tenant_id=tenant_id, slug=slug)
    except WikiPageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _page_response(detail)


@router.post("/pages/{slug}/revisions", response_model=WikiPageResponse)
async def create_revision(
    slug: str,
    payload: WikiRevisionCreateRequest,
    service: Annotated[WikiService, Depends(get_wiki_service)],
) -> WikiPageResponse:
    try:
        detail = await service.create_revision(
            tenant_id=payload.tenant_id,
            slug=slug,
            content=payload.content,
            content_format=payload.content_format,
            content_json=payload.content_json,
            summary=payload.summary,
            author_type=payload.author_type,
        )
    except WikiPageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _page_response(detail)


@router.get("/pages/{slug}/backlinks", response_model=list[WikiBacklinkResponse])
async def list_backlinks(
    slug: str,
    tenant_id: Annotated[str, Query(min_length=1)],
    service: Annotated[WikiService, Depends(get_wiki_service)],
) -> list[WikiBacklinkResponse]:
    try:
        backlinks = await service.get_backlinks(tenant_id=tenant_id, slug=slug)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return [_backlink_response(backlink) for backlink in backlinks]


def _page_response(detail: WikiPageDetail) -> WikiPageResponse:
    page = detail.page
    return WikiPageResponse(
        id=page.id,
        tenant_id=page.tenant_id,
        slug=page.slug,
        title=page.title,
        page_type=page.page_type,
        status=page.status,
        current_revision_id=page.current_revision_id,
        created_at=page.created_at,
        updated_at=page.updated_at,
        current_revision=_revision_response(detail.current_revision),
    )


def _revision_response(revision: WikiRevision | None) -> WikiRevisionResponse | None:
    if revision is None:
        return None

    return WikiRevisionResponse(
        id=revision.id,
        page_id=revision.page_id,
        revision_no=revision.revision_no,
        content_format=revision.content_format,
        content=revision.content,
        content_json=revision.content_json,
        summary=revision.summary,
        author_type=revision.author_type,
        created_at=revision.created_at,
    )


def _backlink_response(backlink: WikiBacklink) -> WikiBacklinkResponse:
    return WikiBacklinkResponse(
        page_id=backlink.page.id,
        slug=backlink.page.slug,
        title=backlink.page.title,
        link_type=backlink.link.link_type,
        created_at=backlink.link.created_at,
    )
