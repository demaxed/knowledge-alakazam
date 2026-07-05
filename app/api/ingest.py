from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db import get_db_session
from app.ingest_service import (
    DocumentIngestService,
    IngestError,
    IngestInputFileError,
    IngestJobRepository,
    IngestResult,
)
from app.rag_runtime import (
    RAGRuntimeConfigurationError,
    RAGRuntimeDisabledError,
    RAGRuntimeError,
    RAGRuntimeRegistry,
    RAGRuntimeUnavailableError,
)
from app.s3_assets import S3AssetStoreError
from app.schemas import IngestResponse

router = APIRouter(tags=["ingest"])


def get_ingest_settings(request: Request) -> Settings:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application settings are not initialized",
        )
    return settings


def get_ingest_runtime_registry(request: Request) -> RAGRuntimeRegistry:
    registry = getattr(request.app.state, "rag_runtime_registry", None)
    if registry is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="RAG runtime registry is not initialized",
        )
    return registry


async def get_ingest_service(
    settings: Annotated[Settings, Depends(get_ingest_settings)],
    registry: Annotated[RAGRuntimeRegistry, Depends(get_ingest_runtime_registry)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentIngestService:
    return DocumentIngestService(
        settings=settings,
        runtime_registry=registry,
        job_repository=IngestJobRepository(session),
    )


@router.post("/ingest", response_model=IngestResponse)
async def ingest(
    response: Response,
    service: Annotated[DocumentIngestService, Depends(get_ingest_service)],
    settings: Annotated[Settings, Depends(get_ingest_settings)],
    file: Annotated[UploadFile, File()],
    tenant_id: Annotated[str, Form(min_length=1)],
    source_id: Annotated[str | None, Form(min_length=1)] = None,
) -> IngestResponse:
    temp_path = await _save_upload_to_temp(file)
    try:
        if settings.ingest_sync:
            result = await service.ingest_document(
                local_path=temp_path,
                tenant_id=tenant_id,
                source_id=source_id,
            )
        else:
            result = await service.create_pending_job(
                local_path=temp_path,
                tenant_id=tenant_id,
                source_id=source_id,
            )
            response.status_code = status.HTTP_202_ACCEPTED
    except (
        RAGRuntimeDisabledError,
        RAGRuntimeConfigurationError,
        RAGRuntimeUnavailableError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except (IngestInputFileError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except S3AssetStoreError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RAGRuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    except IngestError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    finally:
        shutil.rmtree(temp_path.parent, ignore_errors=True)

    return _response(result)


async def _save_upload_to_temp(file: UploadFile) -> Path:
    temp_dir = Path(tempfile.mkdtemp(prefix="ingest-upload-"))
    filename = Path(file.filename or "upload.bin").name or "upload.bin"
    temp_path = temp_dir / filename
    with temp_path.open("wb") as temp_file:
        while chunk := await file.read(1024 * 1024):
            temp_file.write(chunk)
    return temp_path


def _response(result: IngestResult) -> IngestResponse:
    return IngestResponse(
        tenant_id=result.tenant_id,
        source_id=result.source_id,
        raw_uri=result.raw_uri,
        output_dir=str(result.output_dir),
        asset_count=result.asset_count,
        asset_urls=result.asset_urls,
        status=result.status,
        job_id=result.job_id,
    )
