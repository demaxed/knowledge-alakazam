from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.app_database_url,
        pool_pre_ping=True,
    )


async def init_db(settings: Settings | None = None) -> None:
    global _engine, _session_factory

    if _engine is not None and _session_factory is not None:
        return

    resolved_settings = settings or get_settings()
    _engine = create_engine(resolved_settings)
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)


async def dispose_db() -> None:
    global _engine, _session_factory

    if _engine is not None:
        await _engine.dispose()

    _engine = None
    _session_factory = None


async def get_db_session() -> AsyncIterator[AsyncSession]:
    if _session_factory is None:
        await init_db()

    if _session_factory is None:
        raise RuntimeError("Database session factory was not initialized")

    async with _session_factory() as session:
        yield session
