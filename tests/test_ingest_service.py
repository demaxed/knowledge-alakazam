from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.config import Settings
from app.ingest_service import DocumentIngestService, IngestJobStatus
from app.s3_assets import AssetUploadResult, RawUploadResult


@dataclass(slots=True)
class FakeJob:
    id: UUID
    status: IngestJobStatus
    error: str | None = None


class FakeJobRepository:
    def __init__(self) -> None:
        self.job_id = uuid4()
        self.transitions: list[tuple[IngestJobStatus, str | None]] = []

    async def upsert_job(
        self,
        *,
        tenant_id: str,
        source_id: str,
        raw_bucket: str,
        raw_key: str,
        status: IngestJobStatus,
        error: str | None = None,
    ) -> FakeJob:
        self.transitions.append((status, error))
        return FakeJob(id=self.job_id, status=status, error=error)

    async def mark_processing(self, tenant_id: str, source_id: str) -> FakeJob:
        self.transitions.append(("processing", None))
        return FakeJob(id=self.job_id, status="processing")

    async def mark_succeeded(self, tenant_id: str, source_id: str) -> FakeJob:
        self.transitions.append(("succeeded", None))
        return FakeJob(id=self.job_id, status="succeeded")

    async def mark_failed(self, tenant_id: str, source_id: str, error: str) -> FakeJob:
        self.transitions.append(("failed", error))
        return FakeJob(id=self.job_id, status="failed", error=error)


class FakeAssetStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.raw_uploads: list[Path] = []
        self.output_uploads: list[Path] = []
        self.raw_key_thread_ids: list[int] = []
        self.raw_upload_thread_ids: list[int] = []
        self.output_upload_thread_ids: list[int] = []

    def raw_document_key(self, local_path: str | Path, tenant_id: str, source_id: str) -> str:
        self.raw_key_thread_ids.append(threading.get_ident())
        return f"{tenant_id}/{source_id}/{Path(local_path).name}"

    def upload_raw_document(
        self,
        local_path: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> RawUploadResult:
        self.raw_upload_thread_ids.append(threading.get_ident())
        path = Path(local_path)
        self.raw_uploads.append(path)
        return RawUploadResult(
            bucket=self.settings.s3_bucket_raw,
            key=self.raw_document_key(path, tenant_id, source_id),
            tenant_id=tenant_id,
            source_id=source_id,
            content_type="application/pdf",
            size_bytes=path.stat().st_size,
            url=f"http://minio:9000/{self.settings.s3_bucket_raw}/{tenant_id}/{source_id}/{path.name}",
        )

    def upload_output_tree(
        self,
        local_output_root: str | Path,
        tenant_id: str,
        source_id: str,
    ) -> list[AssetUploadResult]:
        self.output_upload_thread_ids.append(threading.get_ident())
        root = Path(local_output_root)
        self.output_uploads.append(root)
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


def make_source_file(tmp_path: Path) -> Path:
    source_file = tmp_path / "incoming" / "report.pdf"
    source_file.parent.mkdir()
    source_file.write_bytes(b"%PDF-1.7")
    return source_file


def make_service(
    *,
    settings: Settings,
    repository: FakeJobRepository,
    runtime: FakeRuntime | None = None,
) -> DocumentIngestService:
    return DocumentIngestService(
        settings=settings,
        asset_store=FakeAssetStore(settings),
        runtime_registry=FakeRuntimeRegistry(runtime or FakeRuntime()),
        job_repository=repository,
    )


def test_prepare_document_stages_file_and_generates_source_id(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repository = FakeJobRepository()
    service = make_service(settings=settings, repository=repository)
    source_file = make_source_file(tmp_path)

    prepared = service.prepare_document(local_path=source_file, tenant_id="tenant-a")

    assert prepared.tenant_id == "tenant-a"
    assert len(prepared.source_id) == 32
    assert prepared.staged_path == (
        settings.rag_input_dir / "tenant-a" / prepared.source_id / "report.pdf"
    )
    assert prepared.staged_path.read_bytes() == b"%PDF-1.7"
    assert prepared.output_dir == settings.rag_output_dir / "tenant-a" / prepared.source_id
    assert prepared.raw_key == f"tenant-a/{prepared.source_id}/report.pdf"


def test_prepare_document_rejects_path_segments(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repository = FakeJobRepository()
    service = make_service(settings=settings, repository=repository)
    source_file = make_source_file(tmp_path)

    with pytest.raises(ValueError, match="tenant_id must be a single path segment"):
        service.prepare_document(
            local_path=source_file,
            tenant_id="../tenant",
            source_id="source-1",
        )


@pytest.mark.asyncio
async def test_ingest_document_records_status_transitions(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repository = FakeJobRepository()
    runtime = FakeRuntime()
    service = make_service(settings=settings, repository=repository, runtime=runtime)
    source_file = make_source_file(tmp_path)

    result = await service.ingest_document(
        local_path=source_file,
        tenant_id="tenant-a",
        source_id="source-1",
    )

    assert [status for status, _error in repository.transitions] == [
        "pending",
        "processing",
        "succeeded",
    ]
    assert result.tenant_id == "tenant-a"
    assert result.source_id == "source-1"
    assert result.raw_uri == "s3://raw-bucket/tenant-a/source-1/report.pdf"
    assert result.output_dir == settings.rag_output_dir / "tenant-a" / "source-1"
    assert result.asset_count == 1
    assert result.asset_urls == [
        "http://minio:9000/asset-bucket/output/tenant-a/source-1/images/fig1.png"
    ]
    assert runtime.calls == [
        (
            settings.rag_input_dir / "tenant-a" / "source-1" / "report.pdf",
            settings.rag_output_dir / "tenant-a" / "source-1",
            "source-1",
            "report.pdf",
        )
    ]


@pytest.mark.asyncio
async def test_ingest_document_offloads_blocking_staging_and_asset_operations(
    tmp_path: Path,
) -> None:
    settings = make_settings(tmp_path)
    repository = FakeJobRepository()
    runtime = FakeRuntime()
    asset_store = FakeAssetStore(settings)
    service = DocumentIngestService(
        settings=settings,
        asset_store=asset_store,
        runtime_registry=FakeRuntimeRegistry(runtime),
        job_repository=repository,
    )
    source_file = make_source_file(tmp_path)
    event_loop_thread_id = threading.get_ident()

    await service.ingest_document(
        local_path=source_file,
        tenant_id="tenant-a",
        source_id="source-1",
    )

    assert asset_store.raw_key_thread_ids
    assert asset_store.raw_upload_thread_ids
    assert asset_store.output_upload_thread_ids
    assert asset_store.raw_key_thread_ids[-1] != event_loop_thread_id
    assert asset_store.raw_upload_thread_ids[-1] != event_loop_thread_id
    assert asset_store.output_upload_thread_ids[-1] != event_loop_thread_id


@pytest.mark.asyncio
async def test_ingest_document_marks_job_failed_on_runtime_error(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    repository = FakeJobRepository()
    service = make_service(
        settings=settings,
        repository=repository,
        runtime=FakeRuntime(fail=True),
    )
    source_file = make_source_file(tmp_path)

    with pytest.raises(RuntimeError, match="parser exploded"):
        await service.ingest_document(
            local_path=source_file,
            tenant_id="tenant-a",
            source_id="source-1",
        )

    assert repository.transitions[-1] == ("failed", "parser exploded")
