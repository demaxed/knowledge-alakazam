from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import Settings, get_settings
from app.db import dispose_db, init_db


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    settings: Settings = application.state.settings
    await init_db(settings)
    try:
        yield
    finally:
        await dispose_db()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    application = FastAPI(title=resolved_settings.service_name, lifespan=lifespan)
    application.state.settings = resolved_settings
    application.include_router(health_router)
    return application


app = create_app()
