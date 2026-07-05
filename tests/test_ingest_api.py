from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.api.ingest import get_ingest_service, get_ingest_settings
from app.config import Settings
from app.ingest_service import IngestResult
from app.main import create_app
from app.rag_runtime import RAGRuntimeDisabledError
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
