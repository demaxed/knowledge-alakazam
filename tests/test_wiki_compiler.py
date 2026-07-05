from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.api.query import get_rag_runtime_registry
from app.api.wiki import get_wiki_repository, get_wiki_service
from app.config import Settings
from app.main import create_app
from app.rag_runtime import RAGQueryResult
from fastapi.testclient import TestClient
from wiki.compiler import WikiCompiler
from wiki.models import WikiCompileJob
from wiki.service import WikiService

from tests.test_wiki_service import InMemoryWikiRepository, NoopTransaction


class InMemoryCompileJobRepository:
    def __init__(self) -> None:
        self.jobs: dict[UUID, WikiCompileJob] = {}

    def transaction(self) -> NoopTransaction:
        return NoopTransaction()

    async def create_compile_job(
        self,
        *,
        tenant_id: str,
        source_id: str,
        target_slug: str | None = None,
    ) -> WikiCompileJob:
        job = WikiCompileJob(
            id=uuid4(),
            tenant_id=tenant_id,
            source_id=source_id,
            target_slug=target_slug,
            status="pending",
            error=None,
            created_at=_now(),
            updated_at=_now(),
        )
        self.jobs[job.id] = job
        return job

    async def mark_compile_job_processing(self, job_id: UUID) -> WikiCompileJob:
        return self._set_status(job_id, "processing", None)

    async def mark_compile_job_succeeded(self, job_id: UUID) -> WikiCompileJob:
        return self._set_status(job_id, "succeeded", None)

    async def mark_compile_job_failed(self, job_id: UUID, error: str) -> WikiCompileJob:
        return self._set_status(job_id, "failed", error)

    def _set_status(self, job_id: UUID, status: str, error: str | None) -> WikiCompileJob:
        job = self.jobs[job_id]
        job.status = status
        job.error = error
        job.updated_at = _now()
        return job


class FakeRuntime:
    def __init__(
        self,
        *,
        answer: str = "- Alpha is supported by the source.\n- Beta is another claim.",
        metadata: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.answer = answer
        self.metadata = metadata if metadata is not None else _structured_metadata()
        self.error = error
        self.calls: list[tuple[str, str, bool | None]] = []

    async def query(
        self,
        question: str,
        mode: str = "hybrid",
        vlm_enhanced: bool | None = None,
    ) -> RAGQueryResult:
        self.calls.append((question, mode, vlm_enhanced))
        if self.error is not None:
            raise self.error
        return RAGQueryResult(answer=self.answer, metadata=self.metadata)


class FakeRegistry:
    def __init__(self, runtime: FakeRuntime) -> None:
        self.runtime = runtime
        self.requested_tenants: list[str] = []

    async def get(self, tenant_id: str) -> FakeRuntime:
        self.requested_tenants.append(tenant_id)
        return self.runtime


@pytest.mark.asyncio
async def test_compile_source_to_pages_creates_page_claims_and_job() -> None:
    wiki_repository = InMemoryWikiRepository()
    compile_repository = InMemoryCompileJobRepository()
    service = WikiService(wiki_repository)
    runtime = FakeRuntime()
    compiler = WikiCompiler(
        wiki_service=service,
        compile_repository=compile_repository,
        rag_runtime=runtime,
    )

    result = await compiler.compile_source_to_pages(
        tenant_id="tenant-a",
        source_id="source-1",
    )

    assert result.job.status == "succeeded"
    assert result.job.source_id == "source-1"
    assert result.pages[0].slug == "source-source-1"
    assert result.pages[0].title == "Source source-1"
    assert result.pages[0].claim_count == 2
    assert runtime.calls[0][1] == "hybrid"
    assert "source-1" in runtime.calls[0][0]

    detail = await service.get_page(tenant_id="tenant-a", slug="source-source-1")
    assert detail.current_revision is not None
    assert "## Summary" in detail.current_revision.content
    assert "## Source-backed Claims" in detail.current_revision.content
    assert "## Open Questions" in detail.current_revision.content
    assert wiki_repository.claims[0].claim_text == "Alpha is supported by the source."
    assert wiki_repository.claim_sources[0].source_id == "source-1"
    assert wiki_repository.claim_sources[0].chunk_id == "chunk-7"
    assert wiki_repository.claim_sources[0].locator["structured_source_ids_available"] is True


@pytest.mark.asyncio
async def test_compile_topic_page_preserves_unstructured_rag_metadata() -> None:
    wiki_repository = InMemoryWikiRepository()
    compile_repository = InMemoryCompileJobRepository()
    service = WikiService(wiki_repository)
    runtime = FakeRuntime(
        answer="The topic has evidence, but the runtime did not return chunk metadata.",
        metadata={"workspace": "tenant-a"},
    )
    compiler = WikiCompiler(
        wiki_service=service,
        compile_repository=compile_repository,
        rag_runtime=runtime,
    )

    result = await compiler.compile_topic_page(
        tenant_id="tenant-a",
        topic="Safety Controls",
        evidence_query="Find evidence about safety controls.",
        target_slug="safety-controls",
    )

    assert result.job.status == "succeeded"
    assert result.job.source_id == "topic:safety-controls"
    assert result.pages[0].slug == "safety-controls"
    assert result.pages[0].title == "Safety Controls"
    assert wiki_repository.claim_sources[0].source_id == "rag-query"
    locator = wiki_repository.claim_sources[0].locator
    assert locator["structured_source_ids_available"] is False
    assert locator["rag_metadata"] == {"workspace": "tenant-a"}


@pytest.mark.asyncio
async def test_compile_job_is_marked_failed_when_runtime_query_fails() -> None:
    wiki_repository = InMemoryWikiRepository()
    compile_repository = InMemoryCompileJobRepository()
    service = WikiService(wiki_repository)
    compiler = WikiCompiler(
        wiki_service=service,
        compile_repository=compile_repository,
        rag_runtime=FakeRuntime(error=RuntimeError("runtime failed")),
    )

    with pytest.raises(RuntimeError, match="runtime failed"):
        await compiler.compile_source_to_pages(
            tenant_id="tenant-a",
            source_id="source-1",
        )

    jobs = list(compile_repository.jobs.values())
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert jobs[0].error == "runtime failed"


def test_compile_endpoint_compiles_topic_with_source() -> None:
    settings = Settings(
        app_database_url="postgresql+asyncpg://rag:rag@localhost:5432/rag",
        rag_runtime_disabled=False,
    )
    wiki_repository = InMemoryWikiRepository()
    compile_repository = InMemoryCompileJobRepository()
    service = WikiService(wiki_repository)
    runtime = FakeRuntime()
    registry = FakeRegistry(runtime)
    application = create_app(settings)
    application.dependency_overrides[get_wiki_repository] = lambda: compile_repository
    application.dependency_overrides[get_wiki_service] = lambda: service
    application.dependency_overrides[get_rag_runtime_registry] = lambda: registry

    with TestClient(application) as client:
        response = client.post(
            "/wiki/compile",
            json={
                "tenant_id": "tenant-a",
                "source_id": "source-1",
                "topic": "Alpha Topic",
                "target_slug": "alpha-topic",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tenant_id"] == "tenant-a"
    assert payload["source_id"] == "source-1"
    assert payload["target_slug"] == "alpha-topic"
    assert payload["status"] == "succeeded"
    assert payload["pages"][0]["slug"] == "alpha-topic"
    assert payload["pages"][0]["claim_count"] == 2
    assert registry.requested_tenants == ["tenant-a"]


def _structured_metadata() -> dict[str, object]:
    return {
        "sources": [
            {
                "source_id": "source-1",
                "document_uri": "s3://rag-raw/tenant-a/source-1/report.pdf",
                "chunk_id": "chunk-7",
                "quote": "Alpha is supported by the source.",
            }
        ],
        "entities": [{"name": "Alpha Concept"}],
        "open_questions": ["What needs follow-up validation?"],
    }


def _now() -> datetime:
    return datetime.now(UTC)
