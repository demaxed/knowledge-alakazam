from __future__ import annotations

from app.config import Settings
from app.main import create_app
from app.rag_runtime import RAGQueryResult
from fastapi.testclient import TestClient


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_database_url": "postgresql+asyncpg://rag:rag@localhost:5432/rag",
        "rag_runtime_disabled": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_query_endpoint_returns_graceful_error_when_runtime_disabled() -> None:
    application = create_app(make_settings(rag_runtime_disabled=True))

    with TestClient(application) as client:
        response = client.post(
            "/query",
            json={"tenant_id": "tenant-a", "question": "What is indexed?"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "RAG runtime is disabled by RAG_RUNTIME_DISABLED=true",
    }


def test_query_endpoint_uses_runtime_registry() -> None:
    class FakeRuntime:
        async def query(
            self,
            question: str,
            mode: str = "hybrid",
            vlm_enhanced: bool | None = None,
        ) -> RAGQueryResult:
            return RAGQueryResult(
                answer=f"answer: {question}",
                metadata={
                    "tenant_id": "tenant-a",
                    "mode": mode,
                    "vlm_enhanced": vlm_enhanced,
                },
            )

    class FakeRegistry:
        def __init__(self) -> None:
            self.requested_tenant_id: str | None = None
            self.shutdown_called = False

        async def get(self, tenant_id: str) -> FakeRuntime:
            self.requested_tenant_id = tenant_id
            return FakeRuntime()

        async def shutdown(self) -> None:
            self.shutdown_called = True

    fake_registry = FakeRegistry()
    application = create_app(make_settings(rag_runtime_disabled=False))
    application.state.rag_runtime_registry = fake_registry

    with TestClient(application) as client:
        response = client.post(
            "/query",
            json={
                "tenant_id": "tenant-a",
                "question": "What is indexed?",
                "mode": "hybrid",
                "vlm_enhanced": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "answer: What is indexed?",
        "metadata": {
            "tenant_id": "tenant-a",
            "mode": "hybrid",
            "vlm_enhanced": True,
        },
    }
    assert fake_registry.requested_tenant_id == "tenant-a"
    assert fake_registry.shutdown_called is True
