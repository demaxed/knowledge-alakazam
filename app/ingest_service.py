from __future__ import annotations

import hashlib
import shutil
from collections.abc import Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from wiki.models import IngestJob

from app.config import Settings
from app.s3_assets import AssetUploadResult, RawUploadResult, S3AssetStore

IngestJobStatus = Literal["pending", "processing", "succeeded", "failed"]


class IngestError(RuntimeError):
    """Base error for document ingest failures."""


class IngestInputFileError(IngestError):
    """Raised when the source file cannot be staged for ingest."""


class IngestJobNotFoundError(IngestError):
    """Raised when an expected ingest job is missing."""


class AssetStoreProtocol(Protocol):
    def raw_document_key(self, local_path: str | Path, tenant_id: str, source_id: str) -> str: ...

    def upload_raw_document(
        self,
        local_path: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> RawUploadResult: ...

    def upload_output_tree(
        self,
        local_output_root: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> list[AssetUploadResult]: ...


class RAGDocumentRuntimeProtocol(Protocol):
    async def process_document_complete(
        self,
        *,
        file_path: str | Path,
        output_dir: str | Path,
        source_id: str,
        file_name: str | None = None,
    ) -> None: ...


class RuntimeRegistryProtocol(Protocol):
    async def get(self, tenant_id: str) -> RAGDocumentRuntimeProtocol: ...


class IngestJobRepositoryProtocol(Protocol):
    async def upsert_job(
        self,
        *,
        tenant_id: str,
        source_id: str,
        raw_bucket: str,
        raw_key: str,
        status: IngestJobStatus,
        error: str | None = None,
    ) -> IngestJob: ...

    async def mark_processing(self, tenant_id: str, source_id: str) -> IngestJob: ...

    async def mark_succeeded(self, tenant_id: str, source_id: str) -> IngestJob: ...

    async def mark_failed(self, tenant_id: str, source_id: str, error: str) -> IngestJob: ...


@dataclass(frozen=True, slots=True)
class PreparedDocument:
    tenant_id: str
    source_id: str
    staged_path: Path
    output_dir: Path
    raw_bucket: str
    raw_key: str


@dataclass(frozen=True, slots=True)
class IngestResult:
    tenant_id: str
    source_id: str
    raw_uri: str
    output_dir: Path
    asset_count: int
    asset_urls: list[str]
    status: IngestJobStatus
    job_id: UUID | None = None


class IngestJobRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @asynccontextmanager
    async def transaction(self) -> Any:
        if self.session.in_transaction():
            yield
            return

        async with self.session.begin():
            yield

    async def upsert_job(
        self,
        *,
        tenant_id: str,
        source_id: str,
        raw_bucket: str,
        raw_key: str,
        status: IngestJobStatus,
        error: str | None = None,
    ) -> IngestJob:
        async with self.transaction():
            job = await self._get_job(tenant_id, source_id)
            if job is None:
                job = IngestJob(
                    tenant_id=tenant_id,
                    source_id=source_id,
                    raw_bucket=raw_bucket,
                    raw_key=raw_key,
                    status=status,
                    error=error,
                )
                self.session.add(job)
            else:
                job.raw_bucket = raw_bucket
                job.raw_key = raw_key
                job.status = status
                job.error = error

            await self.session.flush()
            return job

    async def mark_processing(self, tenant_id: str, source_id: str) -> IngestJob:
        return await self._update_status(
            tenant_id=tenant_id,
            source_id=source_id,
            status="processing",
            error=None,
        )

    async def mark_succeeded(self, tenant_id: str, source_id: str) -> IngestJob:
        return await self._update_status(
            tenant_id=tenant_id,
            source_id=source_id,
            status="succeeded",
            error=None,
        )

    async def mark_failed(self, tenant_id: str, source_id: str, error: str) -> IngestJob:
        return await self._update_status(
            tenant_id=tenant_id,
            source_id=source_id,
            status="failed",
            error=error,
        )

    async def _update_status(
        self,
        *,
        tenant_id: str,
        source_id: str,
        status: IngestJobStatus,
        error: str | None,
    ) -> IngestJob:
        async with self.transaction():
            job = await self._get_job(tenant_id, source_id)
            if job is None:
                raise IngestJobNotFoundError(
                    f"Ingest job does not exist for tenant={tenant_id!r}, source={source_id!r}"
                )

            job.status = status
            job.error = error
            await self.session.flush()
            return job

    async def _get_job(self, tenant_id: str, source_id: str) -> IngestJob | None:
        result = await self.session.scalars(
            select(IngestJob).where(
                IngestJob.tenant_id == tenant_id,
                IngestJob.source_id == source_id,
            )
        )
        return result.one_or_none()


class DocumentIngestService:
    def __init__(
        self,
        *,
        settings: Settings,
        asset_store: AssetStoreProtocol | None = None,
        runtime_registry: RuntimeRegistryProtocol | None = None,
        job_repository: IngestJobRepositoryProtocol,
    ) -> None:
        self.settings = settings
        self.asset_store = asset_store or S3AssetStore(settings=settings)
        self.runtime_registry = runtime_registry
        self.job_repository = job_repository

    async def create_pending_job(
        self,
        *,
        local_path: str | Path,
        tenant_id: str,
        source_id: str | None = None,
    ) -> IngestResult:
        prepared = self.prepare_document(
            local_path=local_path,
            tenant_id=tenant_id,
            source_id=source_id,
        )
        await self.job_repository.upsert_job(
            tenant_id=prepared.tenant_id,
            source_id=prepared.source_id,
            raw_bucket=prepared.raw_bucket,
            raw_key=prepared.raw_key,
            status="pending",
        )

        try:
            raw_upload = self.asset_store.upload_raw_document(
                prepared.staged_path,
                tenant_id=prepared.tenant_id,
                source_id=prepared.source_id,
            )
        except Exception as exc:
            await self._mark_failed(prepared, exc)
            raise

        job = await self.job_repository.upsert_job(
            tenant_id=prepared.tenant_id,
            source_id=prepared.source_id,
            raw_bucket=raw_upload.bucket,
            raw_key=raw_upload.key,
            status="pending",
        )
        return self._result(
            prepared=prepared,
            raw_upload=raw_upload,
            assets=[],
            status="pending",
            job_id=job.id,
        )

    async def ingest_document(
        self,
        *,
        local_path: str | Path,
        tenant_id: str,
        source_id: str | None = None,
    ) -> IngestResult:
        if self.runtime_registry is None:
            raise IngestError("RAG runtime registry is not configured")

        prepared = self.prepare_document(
            local_path=local_path,
            tenant_id=tenant_id,
            source_id=source_id,
        )
        await self.job_repository.upsert_job(
            tenant_id=prepared.tenant_id,
            source_id=prepared.source_id,
            raw_bucket=prepared.raw_bucket,
            raw_key=prepared.raw_key,
            status="pending",
        )

        raw_upload: RawUploadResult | None = None
        try:
            await self.job_repository.mark_processing(prepared.tenant_id, prepared.source_id)
            raw_upload = self.asset_store.upload_raw_document(
                prepared.staged_path,
                tenant_id=prepared.tenant_id,
                source_id=prepared.source_id,
            )

            prepared.output_dir.mkdir(parents=True, exist_ok=True)
            runtime = await self.runtime_registry.get(prepared.tenant_id)
            await runtime.process_document_complete(
                file_path=prepared.staged_path,
                output_dir=prepared.output_dir,
                source_id=prepared.source_id,
                file_name=prepared.staged_path.name,
            )
            assets = self.asset_store.upload_output_tree(
                self.settings.rag_output_dir,
                tenant_id=prepared.tenant_id,
                source_id=prepared.source_id,
            )
            job = await self.job_repository.mark_succeeded(
                prepared.tenant_id,
                prepared.source_id,
            )
        except Exception as exc:
            await self._mark_failed(prepared, exc)
            raise

        return self._result(
            prepared=prepared,
            raw_upload=raw_upload,
            assets=assets,
            status="succeeded",
            job_id=job.id,
        )

    def prepare_document(
        self,
        *,
        local_path: str | Path,
        tenant_id: str,
        source_id: str | None = None,
    ) -> PreparedDocument:
        source_path = Path(local_path)
        if not source_path.is_file():
            raise IngestInputFileError(f"Input file not found: {source_path}")

        tenant_segment = _safe_path_segment(tenant_id, "tenant_id")
        resolved_source_id = source_id or _source_id_from_file(source_path)
        source_segment = _safe_path_segment(resolved_source_id, "source_id")
        filename = _safe_filename(source_path.name)
        staged_path = self.settings.rag_input_dir / tenant_segment / source_segment / filename
        staged_path.parent.mkdir(parents=True, exist_ok=True)

        if source_path.resolve() != staged_path.resolve():
            shutil.copy2(source_path, staged_path)

        output_dir = self.settings.rag_output_dir / tenant_segment / source_segment
        raw_key = self.asset_store.raw_document_key(
            staged_path,
            tenant_id=tenant_segment,
            source_id=source_segment,
        )
        return PreparedDocument(
            tenant_id=tenant_segment,
            source_id=source_segment,
            staged_path=staged_path,
            output_dir=output_dir,
            raw_bucket=self.settings.s3_bucket_raw,
            raw_key=raw_key,
        )

    async def _mark_failed(self, prepared: PreparedDocument, exc: Exception) -> None:
        with suppress(Exception):
            await self.job_repository.mark_failed(
                prepared.tenant_id,
                prepared.source_id,
                _error_message(exc),
            )

    @staticmethod
    def _result(
        *,
        prepared: PreparedDocument,
        raw_upload: RawUploadResult,
        assets: Sequence[AssetUploadResult],
        status: IngestJobStatus,
        job_id: UUID | None,
    ) -> IngestResult:
        return IngestResult(
            tenant_id=prepared.tenant_id,
            source_id=prepared.source_id,
            raw_uri=f"s3://{raw_upload.bucket}/{raw_upload.key}",
            output_dir=prepared.output_dir,
            asset_count=len(assets),
            asset_urls=[asset.url for asset in assets],
            status=status,
            job_id=job_id,
        )


def _source_id_from_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:32]


def _safe_path_segment(value: str, name: str) -> str:
    segment = value.strip()
    if not segment:
        raise ValueError(f"{name} must not be empty")
    if "/" in segment or "\\" in segment:
        raise ValueError(f"{name} must be a single path segment")
    if segment in {".", ".."}:
        raise ValueError(f"{name} must not be a relative path marker")
    return segment


def _safe_filename(value: str) -> str:
    filename = Path(value).name.strip()
    if not filename or filename in {".", ".."}:
        raise IngestInputFileError("Input filename is invalid")
    return filename


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__
