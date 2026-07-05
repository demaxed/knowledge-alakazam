from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text

from app.config import Settings
from app.db import get_db_session, init_db
from app.s3_assets import S3AssetStore
from app.schemas import HealthComponent, HealthResponse

router = APIRouter(tags=["health"])


class HealthChecker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def check(self) -> HealthResponse:
        components = {
            "db": await self._check_database(),
            "s3": await self._check_s3(),
            "rag_runtime": self._check_rag_runtime(),
        }
        app_status = self._app_status(components)
        return HealthResponse(
            status=app_status,
            service=self.settings.service_name,
            environment=self.settings.env,
            components=components,
        )

    async def _check_database(self) -> HealthComponent:
        try:
            await asyncio.wait_for(
                self._run_database_probe(),
                timeout=self.settings.health_check_timeout_seconds,
            )
        except Exception as exc:
            return HealthComponent(
                status="unreachable",
                details={"error": _safe_error(exc)},
            )

        return HealthComponent(status="reachable")

    async def _run_database_probe(self) -> None:
        await init_db(self.settings)
        async for session in get_db_session():
            await session.execute(text("SELECT 1"))
            return

    async def _check_s3(self) -> HealthComponent:
        if not self.settings.health_check_s3:
            return HealthComponent(status="skipped", details={"reason": "disabled"})

        try:
            bucket_statuses = await asyncio.wait_for(
                asyncio.to_thread(S3AssetStore(self.settings).check_buckets),
                timeout=self.settings.health_check_timeout_seconds,
            )
        except Exception as exc:
            return HealthComponent(
                status="unreachable",
                details={"error": _safe_error(exc)},
            )

        if all(bucket_statuses.values()):
            return HealthComponent(status="reachable", details={"buckets": bucket_statuses})

        return HealthComponent(status="degraded", details={"buckets": bucket_statuses})

    def _check_rag_runtime(self) -> HealthComponent:
        if self.settings.rag_runtime_disabled:
            return HealthComponent(status="disabled")

        return HealthComponent(
            status="enabled",
            details={
                "storages": {
                    "kv": self.settings.lightrag_kv_storage,
                    "vector": self.settings.lightrag_vector_storage,
                    "graph": self.settings.lightrag_graph_storage,
                    "doc_status": self.settings.lightrag_doc_status_storage,
                },
                "embedding_dim": self.settings.embedding_dim,
            },
        )

    @staticmethod
    def _app_status(components: dict[str, HealthComponent]) -> str:
        db_status = components["db"].status
        s3_status = components["s3"].status
        if db_status == "reachable" and s3_status in {"reachable", "skipped"}:
            return "ok"
        return "degraded"


def get_health_checker(request: Request) -> HealthChecker:
    settings = getattr(request.app.state, "settings", None)
    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Application settings are not initialized",
        )
    return HealthChecker(settings)


@router.get("/health", response_model=HealthResponse)
async def health(
    checker: Annotated[HealthChecker, Depends(get_health_checker)],
) -> HealthResponse:
    return await checker.check()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, TimeoutError):
        return "health check timed out"

    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__

    return message
