from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from wiki.compiler import WikiCompiledPage, WikiCompiler, WikiCompileResult
from wiki.models import WikiRevision, WikiValidationResult
from wiki.repository import WikiBacklink, WikiRepository
from wiki.service import WikiPageDetail, WikiPageNotFoundError, WikiService
from wiki.validators import WikiValidationRun, WikiValidationService

from app.api.query import get_rag_runtime_registry
from app.db import get_db_session
from app.rag_runtime import (
    RAGRuntimeConfigurationError,
    RAGRuntimeDisabledError,
    RAGRuntimeError,
    RAGRuntimeRegistry,
    RAGRuntimeUnavailableError,
)
from app.schemas import (
    WikiBacklinkResponse,
    WikiCompiledPageResponse,
    WikiCompileJobStatus,
    WikiCompileRequest,
    WikiCompileResponse,
    WikiPageCreateRequest,
    WikiPageResponse,
    WikiRevisionCreateRequest,
    WikiRevisionResponse,
    WikiValidationResponse,
    WikiValidationResultResponse,
    WikiValidationSeverity,
)

router = APIRouter(prefix="/wiki", tags=["wiki"])


async def get_wiki_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> WikiRepository:
    return WikiRepository(session)


async def get_wiki_service(
    repository: Annotated[WikiRepository, Depends(get_wiki_repository)],
) -> WikiService:
    return WikiService(repository)


async def get_wiki_validation_service(
    repository: Annotated[WikiRepository, Depends(get_wiki_repository)],
) -> WikiValidationService:
    return WikiValidationService(repository)


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


@router.post("/compile", response_model=WikiCompileResponse)
async def compile_wiki(
    payload: WikiCompileRequest,
    service: Annotated[WikiService, Depends(get_wiki_service)],
    repository: Annotated[WikiRepository, Depends(get_wiki_repository)],
    registry: Annotated[RAGRuntimeRegistry, Depends(get_rag_runtime_registry)],
) -> WikiCompileResponse:
    if not payload.source_id and not payload.topic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either source_id or topic is required",
        )

    try:
        runtime = await registry.get(payload.tenant_id)
        compiler = WikiCompiler(
            wiki_service=service,
            compile_repository=repository,
            rag_runtime=runtime,
        )

        if payload.topic:
            result = await compiler.compile_topic_page(
                tenant_id=payload.tenant_id,
                topic=payload.topic,
                evidence_query=_compile_topic_query(payload.topic, payload.source_id),
                source_id=payload.source_id,
                target_slug=payload.target_slug,
            )
        else:
            if payload.source_id is None:
                raise ValueError("source_id is required when topic is omitted")
            result = await compiler.compile_source_to_pages(
                tenant_id=payload.tenant_id,
                source_id=payload.source_id,
                target_slug=payload.target_slug,
            )
    except (
        RAGRuntimeDisabledError,
        RAGRuntimeConfigurationError,
        RAGRuntimeUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RAGRuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return _compile_response(result)


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


@router.post("/pages/{slug}/validate", response_model=WikiValidationResponse)
async def validate_page(
    slug: str,
    tenant_id: Annotated[str, Query(min_length=1)],
    service: Annotated[WikiValidationService, Depends(get_wiki_validation_service)],
) -> WikiValidationResponse:
    try:
        result = await service.validate_page(tenant_id=tenant_id, slug=slug)
    except WikiPageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _validation_response(result)


@router.get("/pages/{slug}/validation-results", response_model=WikiValidationResponse)
async def list_validation_results(
    slug: str,
    tenant_id: Annotated[str, Query(min_length=1)],
    service: Annotated[WikiValidationService, Depends(get_wiki_validation_service)],
) -> WikiValidationResponse:
    try:
        result = await service.list_page_results(tenant_id=tenant_id, slug=slug)
    except WikiPageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return _validation_response(result)


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


def _compile_response(result: WikiCompileResult) -> WikiCompileResponse:
    job = result.job
    return WikiCompileResponse(
        job_id=job.id,
        tenant_id=job.tenant_id,
        source_id=job.source_id,
        target_slug=job.target_slug,
        status=_compile_job_status(job.status),
        error=job.error,
        pages=[_compiled_page_response(page) for page in result.pages],
    )


def _compiled_page_response(page: WikiCompiledPage) -> WikiCompiledPageResponse:
    return WikiCompiledPageResponse(
        page_id=page.page_id,
        slug=page.slug,
        title=page.title,
        revision_id=page.revision_id,
        revision_no=page.revision_no,
        claim_count=page.claim_count,
    )


def _validation_response(result: WikiValidationRun) -> WikiValidationResponse:
    return WikiValidationResponse(
        tenant_id=result.page.tenant_id,
        slug=result.page.slug,
        page_id=result.page.id,
        revision_id=result.revision.id,
        result_count=len(result.results),
        results=[_validation_result_response(row) for row in result.results],
    )


def _validation_result_response(row: WikiValidationResult) -> WikiValidationResultResponse:
    return WikiValidationResultResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        page_id=row.page_id,
        revision_id=row.revision_id,
        validator_name=row.validator_name,
        severity=_validation_severity(row.severity),
        message=row.message,
        metadata=row.metadata_ or {},
        created_at=row.created_at,
    )


def _compile_topic_query(topic: str, source_id: str | None) -> str:
    if source_id:
        return (
            f"Return source-backed evidence about {topic!r} from document {source_id!r}. "
            "Focus on facts, key concepts, relationships, and open questions."
        )
    return (
        f"Return source-backed evidence about {topic!r}. "
        "Focus on facts, key concepts, relationships, and open questions."
    )


def _compile_job_status(status_value: str) -> WikiCompileJobStatus:
    allowed = {"pending", "processing", "succeeded", "failed"}
    if status_value not in allowed:
        raise ValueError(f"Unknown wiki compile job status: {status_value}")
    return cast(WikiCompileJobStatus, status_value)


def _validation_severity(value: str) -> WikiValidationSeverity:
    allowed = {"info", "warning", "error"}
    if value not in allowed:
        raise ValueError(f"Unknown wiki validation severity: {value}")
    return cast(WikiValidationSeverity, value)
