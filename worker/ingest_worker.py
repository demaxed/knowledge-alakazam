from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import FrameType
from typing import Protocol
from uuid import UUID

from app.config import Settings, get_settings
from app.db import create_engine
from app.ingest_service import (
    AssetStoreProtocol,
    DocumentIngestService,
    PreparedDocument,
    RuntimeRegistryProtocol,
)
from app.rag_runtime import RAGRuntimeRegistry
from app.s3_assets import S3AssetStore
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from wiki.models import IngestJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ClaimedIngestJob:
    id: UUID
    tenant_id: str
    source_id: str
    raw_bucket: str
    raw_key: str

    @classmethod
    def from_model(cls, job: IngestJob) -> ClaimedIngestJob:
        return cls(
            id=job.id,
            tenant_id=job.tenant_id,
            source_id=job.source_id,
            raw_bucket=job.raw_bucket,
            raw_key=job.raw_key,
        )


class WorkerAssetStoreProtocol(AssetStoreProtocol, Protocol):
    def download_raw_document(
        self,
        bucket: str,
        key: str,
        destination_path: str | Path,
    ) -> None: ...


class IngestJobQueueProtocol(Protocol):
    async def claim_next_pending(self) -> ClaimedIngestJob | None: ...

    async def mark_succeeded(self, job: ClaimedIngestJob) -> None: ...

    async def mark_failed(self, job: ClaimedIngestJob, error: str) -> None: ...


def pending_job_claim_statement() -> Select[tuple[IngestJob]]:
    return (
        select(IngestJob)
        .where(IngestJob.status == "pending")
        .order_by(IngestJob.created_at.asc(), IngestJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


class DatabaseIngestJobQueue:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def claim_next_pending(self) -> ClaimedIngestJob | None:
        async with self._session_factory() as session, session.begin():
            result = await session.scalars(pending_job_claim_statement())
            job = result.first()
            if job is None:
                return None

            job.status = "processing"
            job.error = None
            await session.flush()
            return ClaimedIngestJob.from_model(job)

    async def mark_succeeded(self, job: ClaimedIngestJob) -> None:
        await self._update_status(job, status="succeeded", error=None)

    async def mark_failed(self, job: ClaimedIngestJob, error: str) -> None:
        await self._update_status(job, status="failed", error=error)

    async def _update_status(
        self,
        claimed_job: ClaimedIngestJob,
        *,
        status: str,
        error: str | None,
    ) -> None:
        async with self._session_factory() as session, session.begin():
            job = await session.get(IngestJob, claimed_job.id)
            if job is None:
                raise RuntimeError(
                    f"Ingest job disappeared before status update: {claimed_job.id}"
                )

            job.status = status
            job.error = error
            await session.flush()


class IngestWorker:
    def __init__(
        self,
        *,
        settings: Settings,
        queue: IngestJobQueueProtocol,
        asset_store: WorkerAssetStoreProtocol | None = None,
        runtime_registry: RuntimeRegistryProtocol | None = None,
        poll_interval_seconds: float | None = None,
    ) -> None:
        self.settings = settings
        self.queue = queue
        self.asset_store = asset_store or S3AssetStore(settings=settings)
        self.runtime_registry = runtime_registry or RAGRuntimeRegistry(settings)
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else settings.worker_poll_interval_seconds
        )

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        resolved_stop_event = stop_event or asyncio.Event()
        while not resolved_stop_event.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Ingest worker iteration failed")
                processed = True

            if not processed:
                await _sleep_until_stop(
                    resolved_stop_event,
                    timeout=self.poll_interval_seconds,
                )

    async def run_once(self) -> bool:
        job = await self.queue.claim_next_pending()
        if job is None:
            return False

        await self.process_job(job)
        return True

    async def process_job(self, job: ClaimedIngestJob) -> None:
        service = DocumentIngestService(
            settings=self.settings,
            asset_store=self.asset_store,
            runtime_registry=self.runtime_registry,
        )

        try:
            prepared = prepared_document_for_job(self.settings, job)
            self.asset_store.download_raw_document(
                job.raw_bucket,
                job.raw_key,
                prepared.staged_path,
            )
            await service.process_prepared_document(prepared)
        except Exception as exc:
            error = _error_message(exc)
            await self.queue.mark_failed(job, error)
            logger.exception(
                "Ingest job failed",
                extra={
                    "job_id": str(job.id),
                    "tenant_id": job.tenant_id,
                    "source_id": job.source_id,
                },
            )
            return

        await self.queue.mark_succeeded(job)
        logger.info(
            "Ingest job succeeded",
            extra={
                "job_id": str(job.id),
                "tenant_id": job.tenant_id,
                "source_id": job.source_id,
            },
        )


def prepared_document_for_job(settings: Settings, job: ClaimedIngestJob) -> PreparedDocument:
    tenant_id = _safe_path_segment(job.tenant_id, "tenant_id")
    source_id = _safe_path_segment(job.source_id, "source_id")
    staged_path = raw_download_path(settings, job)
    return PreparedDocument(
        tenant_id=tenant_id,
        source_id=source_id,
        staged_path=staged_path,
        output_dir=settings.rag_output_dir / tenant_id / source_id,
        raw_bucket=job.raw_bucket,
        raw_key=job.raw_key,
    )


def raw_download_path(settings: Settings, job: ClaimedIngestJob) -> Path:
    tenant_id = _safe_path_segment(job.tenant_id, "tenant_id")
    source_id = _safe_path_segment(job.source_id, "source_id")
    filename = _safe_filename_from_key(job.raw_key)
    return settings.rag_input_dir / tenant_id / source_id / filename


async def run_cli() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)

    engine = create_engine(settings)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    runtime_registry = RAGRuntimeRegistry(settings)
    queue = DatabaseIngestJobQueue(session_factory)
    worker = IngestWorker(
        settings=settings,
        queue=queue,
        runtime_registry=runtime_registry,
    )

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    logger.info("Starting ingest worker")
    try:
        await worker.run(stop_event)
    finally:
        await runtime_registry.shutdown()
        await engine.dispose()
        logger.info("Ingest worker stopped")


def main() -> None:
    with suppress(KeyboardInterrupt):
        asyncio.run(run_cli())


async def _sleep_until_stop(stop_event: asyncio.Event, *, timeout: float) -> None:
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=timeout)
    except TimeoutError:
        return


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:
            signal.signal(signum, _signal_handler(stop_event))


def _signal_handler(stop_event: asyncio.Event) -> Callable[[int, FrameType | None], None]:
    def handle_signal(_signum: int, _frame: FrameType | None) -> None:
        stop_event.set()

    return handle_signal


def _safe_path_segment(value: str, name: str) -> str:
    segment = value.strip()
    if not segment:
        raise ValueError(f"{name} must not be empty")
    if "/" in segment or "\\" in segment:
        raise ValueError(f"{name} must be a single path segment")
    if segment in {".", ".."}:
        raise ValueError(f"{name} must not be a relative path marker")
    return segment


def _safe_filename_from_key(key: str) -> str:
    stripped_key = key.strip()
    if not stripped_key or stripped_key.endswith("/"):
        raise ValueError("raw_key must include a filename")

    filename = PurePosixPath(stripped_key).name.strip()
    if not filename or filename in {".", ".."}:
        raise ValueError("raw_key must include a filename")
    if "/" in filename or "\\" in filename:
        raise ValueError("raw_key filename must be a single path segment")
    return filename


def _error_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


if __name__ == "__main__":
    main()
