from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from sqlalchemy.engine import make_url

from app.config import Settings

QueryMode = str
logger = logging.getLogger(__name__)


class RAGRuntimeError(RuntimeError):
    """Base error for runtime initialization and query failures."""


class RAGRuntimeDisabledError(RAGRuntimeError):
    """Raised when the runtime is intentionally disabled by configuration."""


class RAGRuntimeConfigurationError(RAGRuntimeError):
    """Raised when the runtime cannot be configured from settings."""


class RAGRuntimeUnavailableError(RAGRuntimeError):
    """Raised when optional RAG packages or backends are unavailable."""


@dataclass(frozen=True)
class RAGQueryResult:
    answer: str
    metadata: dict[str, Any]


class OpenAICompatibleProvider:
    """OpenAI-compatible LightRAG model functions.

    The provider is intentionally isolated so a non-OpenAI backend can be added later
    without changing the runtime lifecycle or API layer.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def llm_model_func(self) -> Callable[..., Any]:
        async def complete(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            **kwargs: Any,
        ) -> str:
            openai_module: Any = import_module("lightrag.llm.openai")

            return await openai_module.openai_complete_if_cache(
                self._settings.llm_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=self._api_key(),
                base_url=self._settings.openai_base_url,
                **kwargs,
            )

        return complete

    def vision_model_func(self) -> Callable[..., Any]:
        async def complete(
            prompt: str,
            system_prompt: str | None = None,
            history_messages: list[dict[str, Any]] | None = None,
            image_data: str | None = None,
            **kwargs: Any,
        ) -> str:
            openai_module: Any = import_module("lightrag.llm.openai")

            image_inputs = list(kwargs.pop("image_inputs", []) or [])
            if image_data:
                image_inputs.append(image_data)

            return await openai_module.openai_complete_if_cache(
                self._settings.vision_model,
                prompt,
                system_prompt=system_prompt,
                history_messages=history_messages or [],
                api_key=self._api_key(),
                base_url=self._settings.openai_base_url,
                image_inputs=image_inputs or None,
                **kwargs,
            )

        return complete

    def embedding_func(self) -> Any:
        openai_module: Any = import_module("lightrag.llm.openai")
        utils_module: Any = import_module("lightrag.utils")

        @utils_module.wrap_embedding_func_with_attrs(
            embedding_dim=self._settings.embedding_dim,
            max_token_size=8192,
            model_name=self._settings.embedding_model,
            send_dimensions=True,
            supports_asymmetric=True,
        )
        async def embed(
            texts: list[str],
            embedding_dim: int | None = None,
            max_token_size: int | None = None,
            context: str = "document",
            **kwargs: Any,
        ) -> Any:
            return await openai_module.openai_embed.func(
                texts,
                model=self._settings.embedding_model,
                api_key=self._api_key(),
                base_url=self._settings.openai_base_url,
                embedding_dim=embedding_dim,
                max_token_size=max_token_size,
                context=context,
                **kwargs,
            )

        return embed

    def _api_key(self) -> str:
        if self._settings.openai_api_key is None:
            raise RAGRuntimeConfigurationError(
                "OPENAI_API_KEY is required when RAG runtime is enabled"
            )

        api_key = self._settings.openai_api_key.get_secret_value()
        if not api_key.strip():
            raise RAGRuntimeConfigurationError(
                "OPENAI_API_KEY is required when RAG runtime is enabled"
            )
        return api_key


class RAGRuntime:
    """Tenant-scoped LightRAG and RAG-Anything runtime."""

    def __init__(
        self,
        settings: Settings,
        tenant_id: str,
        provider: OpenAICompatibleProvider | None = None,
    ) -> None:
        self.settings = settings
        self.tenant_id = tenant_id
        self.workspace = workspace_for_tenant(tenant_id)
        self.provider = provider or OpenAICompatibleProvider(settings)
        self.lightrag: Any | None = None
        self.rag_anything: Any | None = None
        self._initialized = False
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self.settings.rag_runtime_disabled:
            logger.info(
                "rag_runtime_initialization_skipped",
                extra={
                    "tenant_id": self.tenant_id,
                    "workspace": self.workspace,
                    "reason": "disabled",
                },
            )
            raise RAGRuntimeDisabledError("RAG runtime is disabled by RAG_RUNTIME_DISABLED=true")

        async with self._lock:
            if self._initialized:
                return

            logger.info(
                "rag_runtime_initializing",
                extra={
                    "tenant_id": self.tenant_id,
                    "workspace": self.workspace,
                    "storages": {
                        "kv": self.settings.lightrag_kv_storage,
                        "vector": self.settings.lightrag_vector_storage,
                        "graph": self.settings.lightrag_graph_storage,
                        "doc_status": self.settings.lightrag_doc_status_storage,
                    },
                },
            )
            self._apply_package_environment()

            try:
                lightrag_module: Any = import_module("lightrag")
                raganything_module: Any = import_module("raganything")
                LightRAG = lightrag_module.LightRAG
                RAGAnything = raganything_module.RAGAnything
                RAGAnythingConfig = raganything_module.RAGAnythingConfig
            except ImportError as exc:
                raise RAGRuntimeUnavailableError(
                    "RAG runtime packages are not installed. Run `uv sync --extra rag`."
                ) from exc

            self.settings.rag_working_dir.mkdir(parents=True, exist_ok=True)
            self.settings.rag_output_dir.mkdir(parents=True, exist_ok=True)
            self.settings.rag_input_dir.mkdir(parents=True, exist_ok=True)

            llm_model_func = self.provider.llm_model_func()
            vision_model_func = self.provider.vision_model_func()
            embedding_func = self.provider.embedding_func()

            self.lightrag = LightRAG(
                working_dir=str(self.settings.rag_working_dir),
                kv_storage=self.settings.lightrag_kv_storage,
                vector_storage=self.settings.lightrag_vector_storage,
                graph_storage=self.settings.lightrag_graph_storage,
                doc_status_storage=self.settings.lightrag_doc_status_storage,
                workspace=self.workspace,
                llm_model_func=llm_model_func,
                embedding_func=embedding_func,
                llm_model_name=self.settings.llm_model,
            )
            await self.lightrag.initialize_storages()

            rag_config = RAGAnythingConfig(
                working_dir=str(self.settings.rag_working_dir),
                parser_output_dir=str(self.settings.rag_output_dir),
                parser=self.settings.parser,
                parse_method=self.settings.parse_method,
                enable_image_processing=self.settings.rag_enable_image_processing,
                enable_table_processing=self.settings.rag_enable_table_processing,
                enable_equation_processing=self.settings.rag_enable_equation_processing,
            )
            self.rag_anything = RAGAnything(
                lightrag=self.lightrag,
                llm_model_func=llm_model_func,
                vision_model_func=vision_model_func,
                embedding_func=embedding_func,
                config=rag_config,
            )

            ensure_initialized = getattr(self.rag_anything, "_ensure_lightrag_initialized", None)
            if callable(ensure_initialized):
                result = await ensure_initialized()
                if not result or not result.get("success"):
                    error = (result or {}).get("error", "unknown error")
                    raise RAGRuntimeUnavailableError(
                        f"RAG-Anything initialization failed: {error}"
                    )

            self._initialized = True
            logger.info(
                "rag_runtime_initialized",
                extra={
                    "tenant_id": self.tenant_id,
                    "workspace": self.workspace,
                    "embedding_dim": self.settings.embedding_dim,
                },
            )

    async def query(
        self,
        question: str,
        mode: QueryMode = "hybrid",
        vlm_enhanced: bool | None = None,
    ) -> RAGQueryResult:
        await self.initialize()

        if self.rag_anything is None:
            raise RAGRuntimeUnavailableError("RAG-Anything runtime was not initialized")

        query_kwargs: dict[str, Any] = {}
        if vlm_enhanced is not None:
            query_kwargs["vlm_enhanced"] = vlm_enhanced

        raw_answer = await self.rag_anything.aquery(question, mode=mode, **query_kwargs)
        answer = await _coerce_answer(raw_answer)

        return RAGQueryResult(
            answer=answer,
            metadata={
                "tenant_id": self.tenant_id,
                "workspace": self.workspace,
                "mode": mode,
                "vlm_enhanced": vlm_enhanced,
                "runtime": "raganything+lightrag",
                "storages": {
                    "kv": self.settings.lightrag_kv_storage,
                    "vector": self.settings.lightrag_vector_storage,
                    "graph": self.settings.lightrag_graph_storage,
                    "doc_status": self.settings.lightrag_doc_status_storage,
                },
            },
        )

    async def process_document_complete(
        self,
        *,
        file_path: str | Path,
        output_dir: str | Path,
        source_id: str,
        file_name: str | None = None,
    ) -> None:
        await self.initialize()

        if self.rag_anything is None:
            raise RAGRuntimeUnavailableError("RAG-Anything runtime was not initialized")

        await self.rag_anything.process_document_complete(
            file_path=str(file_path),
            output_dir=str(output_dir),
            parse_method=self.settings.parse_method,
            doc_id=source_id,
            file_name=file_name or Path(file_path).name,
        )

    async def shutdown(self) -> None:
        async with self._lock:
            if self.rag_anything is not None and hasattr(self.rag_anything, "finalize_storages"):
                await self.rag_anything.finalize_storages()
            elif self.lightrag is not None and hasattr(self.lightrag, "finalize_storages"):
                await self.lightrag.finalize_storages()

            self.rag_anything = None
            self.lightrag = None
            self._initialized = False

    def _apply_package_environment(self) -> None:
        os.environ["LIGHTRAG_KV_STORAGE"] = self.settings.lightrag_kv_storage
        os.environ["LIGHTRAG_VECTOR_STORAGE"] = self.settings.lightrag_vector_storage
        os.environ["LIGHTRAG_GRAPH_STORAGE"] = self.settings.lightrag_graph_storage
        os.environ["LIGHTRAG_DOC_STATUS_STORAGE"] = self.settings.lightrag_doc_status_storage

        parsed_url = make_url(self.settings.app_database_url)
        if parsed_url.host:
            os.environ["POSTGRES_HOST"] = parsed_url.host
        if parsed_url.port:
            os.environ["POSTGRES_PORT"] = str(parsed_url.port)
        if parsed_url.username:
            os.environ["POSTGRES_USER"] = unquote(parsed_url.username)
        if parsed_url.password:
            os.environ["POSTGRES_PASSWORD"] = unquote(parsed_url.password)
        if parsed_url.database:
            os.environ["POSTGRES_DATABASE"] = parsed_url.database


class RAGRuntimeRegistry:
    """Lazy process-local runtime registry keyed by tenant workspace."""

    def __init__(
        self,
        settings: Settings,
        runtime_factory: Callable[[Settings, str], RAGRuntime] | None = None,
    ) -> None:
        self._settings = settings
        self._runtime_factory = runtime_factory or RAGRuntime
        self._runtimes: dict[str, RAGRuntime] = {}
        self._lock = asyncio.Lock()

    async def get(self, tenant_id: str) -> RAGRuntime:
        if self._settings.rag_runtime_disabled:
            raise RAGRuntimeDisabledError(
                "RAG runtime is disabled by RAG_RUNTIME_DISABLED=true"
            )

        workspace = workspace_for_tenant(tenant_id)
        async with self._lock:
            runtime = self._runtimes.get(workspace)
            if runtime is None:
                runtime = self._runtime_factory(self._settings, tenant_id)
                self._runtimes[workspace] = runtime

        await runtime.initialize()
        return runtime

    async def shutdown(self) -> None:
        async with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()

        for runtime in runtimes:
            await runtime.shutdown()


def workspace_for_tenant(tenant_id: str) -> str:
    stripped = tenant_id.strip()
    if not stripped:
        raise ValueError("tenant_id must not be empty")

    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", stripped).strip("._-")
    if not normalized:
        normalized = "tenant"
    digest = hashlib.sha256(stripped.encode("utf-8")).hexdigest()[:12]
    return f"tenant_{normalized[:40]}_{digest}"


async def _coerce_answer(raw_answer: Any) -> str:
    if isinstance(raw_answer, str):
        return raw_answer

    if hasattr(raw_answer, "__aiter__"):
        chunks: list[str] = []
        async for chunk in raw_answer:
            chunks.append(str(chunk))
        return "".join(chunks)

    return str(raw_answer)
