from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.ingest import router as ingest_router
from app.api.query import router as query_router
from app.api.wiki import router as wiki_router
from app.config import Settings, get_settings
from app.db import dispose_db, init_db
from app.observability import RequestIdMiddleware, configure_logging
from app.rag_runtime import RAGRuntimeRegistry


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    await init_db(settings)
    try:
        yield
    finally:
        registry = getattr(application.state, "rag_runtime_registry", None)
        if registry is not None:
            await registry.shutdown()
        await dispose_db()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings)
    application = FastAPI(title=resolved_settings.service_name, lifespan=lifespan)
    application.state.settings = resolved_settings
    application.state.rag_runtime_registry = RAGRuntimeRegistry(resolved_settings)
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health_router)
    application.include_router(ingest_router)
    application.include_router(query_router)
    application.include_router(wiki_router)
    return application


app = create_app()
