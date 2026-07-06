from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import pytest
from app.api import ingest as ingest_module
from app.api.ingest import get_ingest_service, get_ingest_settings
from app.config import Settings
from app.ingest_service import IngestResult
from app.main import create_app
from app.rag_runtime import RAGRuntimeDisabledError
from fastapi import UploadFile
from fastapi.testclient import TestClient


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_database_url": "postgresql+asyncpg://rag:rag@localhost:5432/rag",
        "rag_input_dir": tmp_path / "inputs",
        "rag_output_dir": tmp_path / "output",
        "rag_working_dir": tmp_path / "lightrag",
        "ingest_sync": True,
        "rag_runtime_disabled": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_ingest_endpoint_returns_runtime_disabled_error(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, ingest_sync=True)

    class FakeService:
        async def ingest_document(
            self,
            *,
            local_path: str | Path,
            tenant_id: str,
            source_id: str | None = None,
        ) -> IngestResult:
            raise RAGRuntimeDisabledError("RAG runtime is disabled by RAG_RUNTIME_DISABLED=true")

    application = create_app(settings)
    application.dependency_overrides[get_ingest_settings] = lambda: settings
    application.dependency_overrides[get_ingest_service] = lambda: FakeService()

    with TestClient(application) as client:
        response = client.post(
            "/ingest",
            data={"tenant_id": "tenant-a", "source_id": "source-1"},
            files={"file": ("report.pdf", b"%PDF-1.7", "application/pdf")},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "RAG runtime is disabled by RAG_RUNTIME_DISABLED=true",
    }


def test_ingest_endpoint_can_create_pending_job(tmp_path: Path) -> None:
    settings = make_settings(tmp_path, ingest_sync=False)
    requested: dict[str, object] = {}

    class FakeService:
        async def create_pending_job(
            self,
            *,
            local_path: str | Path,
            tenant_id: str,
            source_id: str | None = None,
        ) -> IngestResult:
            requested["local_path_name"] = Path(local_path).name
            requested["tenant_id"] = tenant_id
            requested["source_id"] = source_id
            return IngestResult(
                tenant_id=tenant_id,
                source_id=source_id or "generated",
                raw_uri="s3://raw-bucket/tenant-a/source-1/report.pdf",
                output_dir=settings.rag_output_dir / tenant_id / (source_id or "generated"),
                asset_count=0,
                asset_urls=[],
                status="pending",
                job_id=uuid4(),
            )

    application = create_app(settings)
    application.dependency_overrides[get_ingest_settings] = lambda: settings
    application.dependency_overrides[get_ingest_service] = lambda: FakeService()

    with TestClient(application) as client:
        response = client.post(
            "/ingest",
            data={"tenant_id": "tenant-a", "source_id": "source-1"},
            files={"file": ("report.pdf", b"%PDF-1.7", "application/pdf")},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["tenant_id"] == "tenant-a"
    assert payload["source_id"] == "source-1"
    assert payload["raw_uri"] == "s3://raw-bucket/tenant-a/source-1/report.pdf"
    assert payload["asset_count"] == 0
    assert payload["asset_urls"] == []
    assert payload["status"] == "pending"
    assert requested == {
        "local_path_name": "report.pdf",
        "tenant_id": "tenant-a",
        "source_id": "source-1",
    }


@pytest.mark.asyncio
async def test_save_upload_to_temp_uses_threaded_file_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_to_thread = asyncio.to_thread
    threaded_call_names: list[str] = []

    async def tracking_to_thread(function: object, /, *args: object, **kwargs: object) -> object:
        threaded_call_names.append(getattr(function, "__name__", repr(function)))
        return await original_to_thread(function, *args, **kwargs)

    monkeypatch.setattr(ingest_module.asyncio, "to_thread", tracking_to_thread)
    upload = UploadFile(filename="report.pdf", file=BytesIO(b"%PDF-1.7"))

    temp_path = await ingest_module._save_upload_to_temp(upload)
    try:
        assert temp_path.name == "report.pdf"
        assert temp_path.read_bytes() == b"%PDF-1.7"
    finally:
        await ingest_module._remove_tree(temp_path.parent)

    assert "mkdtemp" in threaded_call_names
    assert "open" in threaded_call_names
    assert "write" in threaded_call_names
    assert "close" in threaded_call_names
    assert "rmtree" in threaded_call_names


@pytest.mark.asyncio
async def test_save_upload_to_temp_cleans_up_after_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    temp_dir = tmp_path / "ingest-upload"

    def fake_mkdtemp(*, prefix: str) -> str:
        assert prefix == "ingest-upload-"
        temp_dir.mkdir()
        return str(temp_dir)

    class CancellingUpload:
        filename = "report.pdf"

        async def read(self, _size: int) -> bytes:
            raise asyncio.CancelledError

    monkeypatch.setattr(ingest_module.tempfile, "mkdtemp", fake_mkdtemp)

    with pytest.raises(asyncio.CancelledError):
        await ingest_module._save_upload_to_temp(CancellingUpload())

    assert not temp_dir.exists()
