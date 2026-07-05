from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.rag_runtime import (
    RAGRuntimeConfigurationError,
    RAGRuntimeDisabledError,
    RAGRuntimeError,
    RAGRuntimeRegistry,
    RAGRuntimeUnavailableError,
)
from app.schemas import QueryRequest, QueryResponse

router = APIRouter(tags=["query"])


def get_rag_runtime_registry(request: Request) -> RAGRuntimeRegistry:
    registry = getattr(request.app.state, "rag_runtime_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG runtime registry is not initialized",
        )
    return registry


@router.post("/query", response_model=QueryResponse)
async def query(
    payload: QueryRequest,
    registry: Annotated[RAGRuntimeRegistry, Depends(get_rag_runtime_registry)],
) -> QueryResponse:
    try:
        runtime = await registry.get(payload.tenant_id)
        result = await runtime.query(
            question=payload.question,
            mode=payload.mode,
            vlm_enhanced=payload.vlm_enhanced,
        )
    except RAGRuntimeDisabledError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except RAGRuntimeConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except RAGRuntimeUnavailableError as exc:
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

    return QueryResponse(answer=result.answer, metadata=result.metadata)
