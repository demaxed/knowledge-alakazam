from __future__ import annotations

import os

import pytest
from app.config import Settings
from app.rag_runtime import (
    RAGRuntime,
    RAGRuntimeDisabledError,
    RAGRuntimeRegistry,
    workspace_for_tenant,
)


def make_settings(**overrides: object) -> Settings:
    defaults: dict[str, object] = {
        "app_database_url": "postgresql+asyncpg://rag:p%40ss@db.example:5544/rag",
        "rag_runtime_disabled": True,
    }
    defaults.update(overrides)
    return Settings(**defaults)


@pytest.mark.asyncio
async def test_runtime_disabled_raises_before_initializing_packages() -> None:
    runtime = RAGRuntime(settings=make_settings(), tenant_id="tenant-a")

    with pytest.raises(RAGRuntimeDisabledError):
        await runtime.initialize()


def test_workspace_for_tenant_is_single_path_component() -> None:
    workspace = workspace_for_tenant(" tenant/a b ")

    assert workspace.startswith("tenant_tenant_a_b_")
    assert "/" not in workspace
    assert "\\" not in workspace

    with pytest.raises(ValueError):
        workspace_for_tenant("   ")


def test_runtime_applies_lightrag_postgres_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DATABASE",
        "LIGHTRAG_KV_STORAGE",
        "LIGHTRAG_VECTOR_STORAGE",
        "LIGHTRAG_GRAPH_STORAGE",
        "LIGHTRAG_DOC_STATUS_STORAGE",
    ):
        monkeypatch.delenv(key, raising=False)

    runtime = RAGRuntime(settings=make_settings(), tenant_id="tenant-a")

    runtime._apply_package_environment()

    assert os.environ["POSTGRES_HOST"] == "db.example"
    assert os.environ["POSTGRES_PORT"] == "5544"
    assert os.environ["POSTGRES_USER"] == "rag"
    assert os.environ["POSTGRES_PASSWORD"] == "p@ss"
    assert os.environ["POSTGRES_DATABASE"] == "rag"
    assert os.environ["LIGHTRAG_KV_STORAGE"] == "PGKVStorage"
    assert os.environ["LIGHTRAG_VECTOR_STORAGE"] == "PGVectorStorage"
    assert os.environ["LIGHTRAG_GRAPH_STORAGE"] == "PGGraphStorage"
    assert os.environ["LIGHTRAG_DOC_STATUS_STORAGE"] == "PGDocStatusStorage"


@pytest.mark.asyncio
async def test_runtime_registry_returns_initialized_runtime_once() -> None:
    class FakeRuntime:
        def __init__(self, settings: Settings, tenant_id: str) -> None:
            self.settings = settings
            self.tenant_id = tenant_id
            self.initialized_count = 0
            self.shutdown_count = 0

        async def initialize(self) -> None:
            self.initialized_count += 1

        async def shutdown(self) -> None:
            self.shutdown_count += 1

    settings = make_settings(rag_runtime_disabled=False)
    registry = RAGRuntimeRegistry(settings, runtime_factory=FakeRuntime)

    runtime = await registry.get("tenant-a")
    same_runtime = await registry.get("tenant-a")

    assert runtime is same_runtime
    assert runtime.initialized_count == 2

    await registry.shutdown()

    assert runtime.shutdown_count == 1
