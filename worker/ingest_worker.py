from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from types import FrameType
from typing import Protocol, cast
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
from sqlalchemy import Select, and_, or_, select
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
    attempt_count: int = 0
    max_attempts: int = 1
    locked_by: str | None = None

    @classmethod
    def from_model(cls, job: IngestJob) -> ClaimedIngestJob:
        return cls(
            id=job.id,
            tenant_id=job.tenant_id,
            source_id=job.source_id,
            raw_bucket=job.raw_bucket,
            raw_key=job.raw_key,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            locked_by=job.locked_by,
        )


class WorkerAssetStoreProtocol(AssetStoreProtocol, Protocol):
    def download_raw_document(
        self,
        bucket: str,
        key: str,
        destination_path: str | Path,
    ) -> None: ...


class AsyncWorkerAssetStoreProtocol(Protocol):
    async def download_raw_document_async(
        self,
        bucket: str,
        key: str,
        destination_path: str | Path,
    ) -> None: ...


class IngestJobQueueProtocol(Protocol):
    async def claim_next_pending(self) -> ClaimedIngestJob | None: ...

    async def mark_succeeded(self, job: ClaimedIngestJob) -> None: ...

    async def mark_failed(self, job: ClaimedIngestJob, error: str) -> None: ...


class IngestJobHeartbeatQueueProtocol(Protocol):
    async def heartbeat(self, job: ClaimedIngestJob) -> None: ...


def pending_job_claim_statement(
    *,
    now: datetime,
    lease_expires_before: datetime,
) -> Select[tuple[IngestJob]]:
    pending_ready = and_(
        IngestJob.status == "pending",
        or_(
            IngestJob.next_attempt_at.is_(None),
            IngestJob.next_attempt_at <= now,
        ),
    )
    stale_processing = and_(
        IngestJob.status == "processing",
        or_(
            IngestJob.heartbeat_at.is_(None),
            IngestJob.heartbeat_at <= lease_expires_before,
        ),
    )
    return (
        select(IngestJob)
        .where(or_(pending_ready, stale_processing))
        .order_by(IngestJob.created_at.asc(), IngestJob.id.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )


class DatabaseIngestJobQueue:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        lease_seconds: float = 300.0,
        worker_id: str | None = None,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be greater than 0")
        self._session_factory = session_factory
        self._lease_seconds = lease_seconds
        self._worker_id = worker_id or _default_worker_id()

    async def claim_next_pending(self) -> ClaimedIngestJob | None:
        async with self._session_factory() as session, session.begin():
            while True:
                now = _utc_now()
                result = await session.scalars(
                    pending_job_claim_statement(
                        now=now,
                        lease_expires_before=now - timedelta(seconds=self._lease_seconds),
                    )
                )
                job = result.first()
                if job is None:
                    return None

                if _job_attempts_exhausted(job):
                    _mark_job_failed_after_exhausted_attempts(job)
                    await session.flush()
                    logger.warning(
                        "Ingest job exhausted retry attempts",
                        extra={
                            "job_id": str(job.id),
                            "tenant_id": job.tenant_id,
                            "source_id": job.source_id,
                            "attempt_count": job.attempt_count,
                            "max_attempts": job.max_attempts,
                        },
                    )
                    continue

                _claim_job_for_worker(job, now=now, worker_id=self._worker_id)
                await session.flush()
                return ClaimedIngestJob.from_model(job)

    async def mark_succeeded(self, job: ClaimedIngestJob) -> None:
        await self._update_status(job, status="succeeded", error=None)

    async def mark_failed(self, job: ClaimedIngestJob, error: str) -> None:
        await self._update_status(job, status="failed", error=error)

    async def heartbeat(self, job: ClaimedIngestJob) -> None:
        async with self._session_factory() as session, session.begin():
            persisted_job = await session.get(IngestJob, job.id)
            if persisted_job is None:
                raise RuntimeError(f"Ingest job disappeared before heartbeat: {job.id}")
            _assert_job_lease_owned(persisted_job, job)
            persisted_job.heartbeat_at = _utc_now()
            await session.flush()

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
                raise RuntimeError(f"Ingest job disappeared before status update: {claimed_job.id}")

            _assert_job_lease_owned(job, claimed_job)
            job.status = status
            job.error = error
            job.locked_by = None
            job.next_attempt_at = None
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
        self.heartbeat_interval_seconds = max(
            0.1,
            min(settings.worker_job_lease_seconds / 3, 60.0),
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
        heartbeat_task = self._start_heartbeat(job)

        try:
            try:
                prepared = prepared_document_for_job(self.settings, job)
                await _download_raw_document_async(
                    self.asset_store,
                    job.raw_bucket,
                    job.raw_key,
                    prepared.staged_path,
                )
                await service.process_prepared_document(prepared)
            except Exception as exc:
                await self._stop_heartbeat(heartbeat_task)
                heartbeat_task = None
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

            await self._stop_heartbeat(heartbeat_task)
            heartbeat_task = None
            await self.queue.mark_succeeded(job)
            logger.info(
                "Ingest job succeeded",
                extra={
                    "job_id": str(job.id),
                    "tenant_id": job.tenant_id,
                    "source_id": job.source_id,
                },
            )
        finally:
            if heartbeat_task is not None:
                await self._stop_heartbeat(heartbeat_task)

    def _start_heartbeat(self, job: ClaimedIngestJob) -> asyncio.Task[None] | None:
        heartbeat_queue = _heartbeat_queue(self.queue)
        if heartbeat_queue is None:
            return None
        return asyncio.create_task(
            _heartbeat_job(
                heartbeat_queue,
                job,
                interval_seconds=self.heartbeat_interval_seconds,
            )
        )

    @staticmethod
    async def _stop_heartbeat(heartbeat_task: asyncio.Task[None] | None) -> None:
        if heartbeat_task is None:
            return

        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task


def _heartbeat_queue(queue: IngestJobQueueProtocol) -> IngestJobHeartbeatQueueProtocol | None:
    if callable(getattr(queue, "heartbeat", None)):
        return cast(IngestJobHeartbeatQueueProtocol, queue)
    return None


async def _download_raw_document_async(
    asset_store: WorkerAssetStoreProtocol,
    bucket: str,
    key: str,
    destination_path: str | Path,
) -> None:
    if callable(getattr(asset_store, "download_raw_document_async", None)):
        async_asset_store = cast(AsyncWorkerAssetStoreProtocol, asset_store)
        await async_asset_store.download_raw_document_async(bucket, key, destination_path)
        return

    await asyncio.to_thread(
        asset_store.download_raw_document,
        bucket,
        key,
        destination_path,
    )


async def _heartbeat_job(
    queue: IngestJobHeartbeatQueueProtocol,
    job: ClaimedIngestJob,
    *,
    interval_seconds: float,
) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        try:
            await queue.heartbeat(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Ingest job heartbeat failed",
                extra={
                    "job_id": str(job.id),
                    "tenant_id": job.tenant_id,
                    "source_id": job.source_id,
                },
            )


def _claim_job_for_worker(job: IngestJob, *, now: datetime, worker_id: str) -> None:
    job.status = "processing"
    job.error = None
    job.attempt_count = (job.attempt_count or 0) + 1
    job.claimed_at = now
    job.heartbeat_at = now
    job.locked_by = worker_id
    job.next_attempt_at = None


def _job_attempts_exhausted(job: IngestJob) -> bool:
    max_attempts = max(job.max_attempts or 1, 1)
    return (job.attempt_count or 0) >= max_attempts


def _mark_job_failed_after_exhausted_attempts(job: IngestJob) -> None:
    max_attempts = max(job.max_attempts or 1, 1)
    job.status = "failed"
    job.error = f"Ingest job exceeded max attempts ({max_attempts}) after worker lease expired"
    job.locked_by = None
    job.next_attempt_at = None


def _assert_job_lease_owned(persisted_job: IngestJob, claimed_job: ClaimedIngestJob) -> None:
    if persisted_job.status != "processing":
        raise RuntimeError(
            f"Ingest job is no longer processing and cannot be updated: {claimed_job.id}"
        )
    if persisted_job.locked_by != claimed_job.locked_by:
        raise RuntimeError(f"Ingest job lease is no longer owned by this worker: {claimed_job.id}")


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


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
    queue = DatabaseIngestJobQueue(
        session_factory,
        lease_seconds=settings.worker_job_lease_seconds,
    )
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
