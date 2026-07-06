from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.config import Settings
from app.s3_assets import AssetUploadResult, RawUploadResult
from sqlalchemy.dialects import postgresql
from wiki.models import IngestJob
from worker.ingest_worker import (
    ClaimedIngestJob,
    IngestWorker,
    _claim_job_for_worker,
    _job_attempts_exhausted,
    _mark_job_failed_after_exhausted_attempts,
    pending_job_claim_statement,
    raw_download_path,
)


@dataclass(slots=True)
class FakeJobQueue:
    jobs: list[ClaimedIngestJob]
    succeeded: list[ClaimedIngestJob]
    failed: list[tuple[ClaimedIngestJob, str]]
    heartbeats: list[ClaimedIngestJob]

    async def claim_next_pending(self) -> ClaimedIngestJob | None:
        if not self.jobs:
            return None
        return self.jobs.pop(0)

    async def mark_succeeded(self, job: ClaimedIngestJob) -> None:
        self.succeeded.append(job)

    async def mark_failed(self, job: ClaimedIngestJob, error: str) -> None:
        self.failed.append((job, error))

    async def heartbeat(self, job: ClaimedIngestJob) -> None:
        self.heartbeats.append(job)


class FakeWorkerAssetStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.downloads: list[tuple[str, str, Path]] = []
        self.output_uploads: list[tuple[Path, str, str]] = []

    def raw_document_key(self, local_path: str | Path, tenant_id: str, source_id: str) -> str:
        return f"{tenant_id}/{source_id}/{Path(local_path).name}"

    def upload_raw_document(
        self,
        local_path: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> RawUploadResult:
        path = Path(local_path)
        return RawUploadResult(
            bucket=self.settings.s3_bucket_raw,
            key=self.raw_document_key(path, tenant_id, source_id),
            tenant_id=tenant_id,
            source_id=source_id,
            content_type="application/pdf",
            size_bytes=path.stat().st_size,
            url=f"http://minio:9000/{self.settings.s3_bucket_raw}/{tenant_id}/{source_id}/{path.name}",
        )

    def download_raw_document(
        self,
        bucket: str,
        key: str,
        destination_path: str | Path,
    ) -> None:
        destination = Path(destination_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"%PDF-1.7")
        self.downloads.append((bucket, key, destination))

    def upload_output_tree(
        self,
        local_output_root: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> list[AssetUploadResult]:
        root = Path(local_output_root)
        self.output_uploads.append((root, tenant_id, source_id))
        asset_path = root / tenant_id / source_id / "images" / "fig1.png"
        return [
            AssetUploadResult(
                bucket=self.settings.s3_bucket_assets,
                key=f"output/{tenant_id}/{source_id}/images/fig1.png",
                local_path=asset_path,
                content_type="image/png",
                size_bytes=asset_path.stat().st_size,
                url=(
                    f"http://minio:9000/{self.settings.s3_bucket_assets}/"
                    f"output/{tenant_id}/{source_id}/images/fig1.png"
                ),
            )
        ]


class FakeRuntime:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[Path, Path, str, str | None]] = []

    async def process_document_complete(
        self,
        *,
        file_path: str | Path,
        output_dir: str | Path,
        source_id: str,
        file_name: str | None = None,
    ) -> None:
        self.calls.append((Path(file_path), Path(output_dir), source_id, file_name))
        if self.fail:
            raise RuntimeError("parser exploded")

        asset_path = Path(output_dir) / "images" / "fig1.png"
        asset_path.parent.mkdir(parents=True, exist_ok=True)
        asset_path.write_bytes(b"png")


class FakeRuntimeRegistry:
    def __init__(self, runtime: FakeRuntime) -> None:
        self.runtime = runtime
        self.requested_tenants: list[str] = []

    async def get(self, tenant_id: str) -> FakeRuntime:
        self.requested_tenants.append(tenant_id)
        return self.runtime


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        app_database_url="postgresql+asyncpg://rag:rag@localhost:5432/rag",
        rag_input_dir=tmp_path / "inputs",
        rag_output_dir=tmp_path / "output",
        rag_working_dir=tmp_path / "lightrag",
        s3_bucket_raw="raw-bucket",
        s3_bucket_assets="asset-bucket",
    )


def make_job() -> ClaimedIngestJob:
    return ClaimedIngestJob(
        id=uuid4(),
        tenant_id="tenant-a",
        source_id="source-1",
        raw_bucket="raw-bucket",
        raw_key="tenant-a/source-1/report.pdf",
    )


def make_queue(*jobs: ClaimedIngestJob) -> FakeJobQueue:
    return FakeJobQueue(jobs=list(jobs), succeeded=[], failed=[], heartbeats=[])


def test_pending_job_claim_statement_uses_skip_locked() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    compiled = str(
        pending_job_claim_statement(
            now=now,
            lease_expires_before=now - timedelta(minutes=5),
        ).compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "WHERE ingest_job.status = 'pending'" in compiled
    assert "ingest_job.next_attempt_at IS NULL" in compiled
    assert "ingest_job.status = 'processing'" in compiled
    assert "ingest_job.heartbeat_at IS NULL" in compiled
    assert "LIMIT 1" in compiled
    assert "FOR UPDATE SKIP LOCKED" in compiled


def test_claim_job_for_worker_records_retry_and_lease_metadata() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=UTC)
    job = IngestJob(
        id=uuid4(),
        tenant_id="tenant-a",
        source_id="source-1",
        raw_bucket="raw-bucket",
        raw_key="tenant-a/source-1/report.pdf",
        status="pending",
        attempt_count=1,
        max_attempts=3,
    )

    _claim_job_for_worker(job, now=now, worker_id="worker-a")

    assert job.status == "processing"
    assert job.error is None
    assert job.attempt_count == 2
    assert job.claimed_at == now
    assert job.heartbeat_at == now
    assert job.locked_by == "worker-a"
    assert ClaimedIngestJob.from_model(job).locked_by == "worker-a"


def test_exhausted_job_is_marked_failed_instead_of_reclaimed() -> None:
    job = IngestJob(
        id=uuid4(),
        tenant_id="tenant-a",
        source_id="source-1",
        raw_bucket="raw-bucket",
        raw_key="tenant-a/source-1/report.pdf",
        status="processing",
        attempt_count=3,
        max_attempts=3,
        locked_by="worker-a",
    )

    assert _job_attempts_exhausted(job) is True

    _mark_job_failed_after_exhausted_attempts(job)

    assert job.status == "failed"
    assert job.locked_by is None
    assert job.error == "Ingest job exceeded max attempts (3) after worker lease expired"


def test_raw_download_path_preserves_raw_filename(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    job = make_job()

    assert raw_download_path(settings, job) == (
        settings.rag_input_dir / "tenant-a" / "source-1" / "report.pdf"
    )


@pytest.mark.asyncio
async def test_worker_processes_claimed_job(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    job = make_job()
    queue = make_queue(job)
    store = FakeWorkerAssetStore(settings)
    runtime = FakeRuntime()
    registry = FakeRuntimeRegistry(runtime)
    worker = IngestWorker(
        settings=settings,
        queue=queue,
        asset_store=store,
        runtime_registry=registry,
        poll_interval_seconds=0.01,
    )

    processed = await worker.run_once()

    assert processed is True
    assert queue.succeeded == [job]
    assert queue.failed == []
    assert store.downloads == [
        (
            "raw-bucket",
            "tenant-a/source-1/report.pdf",
            settings.rag_input_dir / "tenant-a" / "source-1" / "report.pdf",
        )
    ]
    assert store.output_uploads == [(settings.rag_output_dir, "tenant-a", "source-1")]
    assert registry.requested_tenants == ["tenant-a"]
    assert runtime.calls == [
        (
            settings.rag_input_dir / "tenant-a" / "source-1" / "report.pdf",
            settings.rag_output_dir / "tenant-a" / "source-1",
            "source-1",
            "report.pdf",
        )
    ]


@pytest.mark.asyncio
async def test_worker_marks_job_failed_on_processing_error(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    job = make_job()
    queue = make_queue(job)
    worker = IngestWorker(
        settings=settings,
        queue=queue,
        asset_store=FakeWorkerAssetStore(settings),
        runtime_registry=FakeRuntimeRegistry(FakeRuntime(fail=True)),
        poll_interval_seconds=0.01,
    )

    processed = await worker.run_once()

    assert processed is True
    assert queue.succeeded == []
    assert queue.failed == [(job, "parser exploded")]


@pytest.mark.asyncio
async def test_worker_marks_job_failed_on_invalid_raw_key(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    job = ClaimedIngestJob(
        id=uuid4(),
        tenant_id="tenant-a",
        source_id="source-1",
        raw_bucket="raw-bucket",
        raw_key="tenant-a/source-1/",
    )
    queue = make_queue(job)
    store = FakeWorkerAssetStore(settings)
    worker = IngestWorker(
        settings=settings,
        queue=queue,
        asset_store=store,
        runtime_registry=FakeRuntimeRegistry(FakeRuntime()),
        poll_interval_seconds=0.01,
    )

    processed = await worker.run_once()

    assert processed is True
    assert queue.succeeded == []
    assert queue.failed == [(job, "raw_key must include a filename")]
    assert store.downloads == []


@pytest.mark.asyncio
async def test_worker_returns_false_without_pending_job(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    worker = IngestWorker(
        settings=settings,
        queue=make_queue(),
        asset_store=FakeWorkerAssetStore(settings),
        runtime_registry=FakeRuntimeRegistry(FakeRuntime()),
        poll_interval_seconds=0.01,
    )

    assert await worker.run_once() is False
