from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import app.rag_runtime as rag_runtime_module
import pytest
from app.config import Settings
from app.rag_runtime import (
    OpenAICompatibleProvider,
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
@pytest.mark.parametrize(
    ("embedding_base_url", "expected_base_url"),
    [
        ("https://embedding.example.test/v1", "https://embedding.example.test/v1"),
        (None, "https://llm.example.test/v1"),
    ],
)
async def test_embedding_func_uses_embedding_base_url_with_openai_fallback(
    monkeypatch: pytest.MonkeyPatch,
    embedding_base_url: str | None,
    expected_base_url: str,
) -> None:
    calls: list[dict[str, Any]] = []

    async def fake_embed(texts: list[str], **kwargs: Any) -> list[list[float]]:
        calls.append({"texts": texts, **kwargs})
        return [[0.1, 0.2, 0.3]]

    def fake_wrap_embedding_func_with_attrs(**attrs: Any) -> Any:
        def decorator(func: Any) -> Any:
            for name, value in attrs.items():
                setattr(func, name, value)
            return func

        return decorator

    def fake_import_module(name: str) -> Any:
        if name == "lightrag.llm.openai":
            return SimpleNamespace(openai_embed=SimpleNamespace(func=fake_embed))
        if name == "lightrag.utils":
            return SimpleNamespace(
                wrap_embedding_func_with_attrs=fake_wrap_embedding_func_with_attrs
            )
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(rag_runtime_module, "import_module", fake_import_module)
    settings = make_settings(
        openai_api_key="test-key",
        openai_base_url="https://llm.example.test/v1",
        embedding_base_url=embedding_base_url,
        embedding_model="embedding-test",
        embedding_dim=3,
    )

    embedding_func = OpenAICompatibleProvider(settings).embedding_func()
    result = await embedding_func(["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    assert calls == [
        {
            "texts": ["hello"],
            "model": "embedding-test",
            "api_key": "test-key",
            "base_url": expected_base_url,
            "embedding_dim": None,
            "max_token_size": None,
            "context": "document",
        }
    ]
    assert embedding_func.embedding_dim == 3
    assert embedding_func.model_name == "embedding-test"


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
async def test_runtime_installs_raganything_auxiliary_caches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class FakeProvider:
        def llm_model_func(self) -> object:
            return object()

        def vision_model_func(self) -> object:
            return object()

        def embedding_func(self) -> object:
            return object()

    class FakeLightRAG:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)
            self.initialize_count = 0

        async def initialize_storages(self) -> None:
            self.initialize_count += 1

    class FakeRAGAnythingConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    class FakeParser:
        def check_installation(self) -> bool:
            return True

    class FakeRAGAnything:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)
            self.doc_parser = FakeParser()
            self.parse_cache = None
            self.multimodal_status_cache = None
            self.ensure_parse_cache: Any = None
            self.ensure_multimodal_status_cache: Any = None

        async def _ensure_lightrag_initialized(self) -> dict[str, bool]:
            self.ensure_parse_cache = self.parse_cache
            self.ensure_multimodal_status_cache = self.multimodal_status_cache
            return {"success": True}

    class FakeAuxiliaryStorage:
        instances: list[FakeAuxiliaryStorage] = []

        def __init__(
            self,
            *,
            namespace: str,
            workspace: str,
            global_config: dict[str, Any],
            embedding_func: Any,
        ) -> None:
            self.namespace = namespace
            self.workspace = workspace
            self.global_config = global_config
            self.embedding_func = embedding_func
            self.initialized = False
            self.instances.append(self)

        async def initialize(self) -> None:
            self.initialized = True

    def fake_import_module(name: str) -> Any:
        if name == "lightrag":
            return SimpleNamespace(LightRAG=FakeLightRAG)
        if name == "raganything":
            return SimpleNamespace(
                RAGAnything=FakeRAGAnything,
                RAGAnythingConfig=FakeRAGAnythingConfig,
            )
        if name == "lightrag.kg.json_kv_impl":
            return SimpleNamespace(JsonKVStorage=FakeAuxiliaryStorage)
        raise AssertionError(f"Unexpected import: {name}")

    monkeypatch.setattr(rag_runtime_module, "import_module", fake_import_module)
    settings = make_settings(
        rag_runtime_disabled=False,
        rag_working_dir=tmp_path / "lightrag",
        rag_output_dir=tmp_path / "output",
        rag_input_dir=tmp_path / "input",
    )
    runtime = RAGRuntime(settings=settings, tenant_id="tenant-a", provider=FakeProvider())

    await runtime.initialize()

    assert [storage.namespace for storage in FakeAuxiliaryStorage.instances] == [
        "parse_cache",
        "multimodal_status",
    ]
    assert all(storage.initialized for storage in FakeAuxiliaryStorage.instances)
    assert all(storage.workspace == runtime.workspace for storage in FakeAuxiliaryStorage.instances)
    assert runtime.rag_anything.ensure_parse_cache is FakeAuxiliaryStorage.instances[0]
    assert runtime.rag_anything.ensure_multimodal_status_cache is FakeAuxiliaryStorage.instances[1]


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
