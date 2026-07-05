from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import Settings

REQUEST_ID_HEADER = "X-Request-ID"

_LOG_RECORD_RESERVED = {
    "args",
    "asctime",
    "created",
    "exc_info",
    "exc_text",
    "filename",
    "funcName",
    "levelname",
    "levelno",
    "lineno",
    "module",
    "msecs",
    "message",
    "msg",
    "name",
    "pathname",
    "process",
    "processName",
    "relativeCreated",
    "stack_info",
    "thread",
    "threadName",
}
_SECRET_FIELD_MARKERS = ("authorization", "api_key", "password", "secret", "token", "cookie")


class JsonLogFormatter(logging.Formatter):
    """Small JSON formatter for application-owned logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info is not None:
            payload["exception"] = self.formatException(record.exc_info)

        for key, value in record.__dict__.items():
            if key in _LOG_RECORD_RESERVED or key.startswith("_"):
                continue
            payload[key] = _sanitize_log_value(key, value)

        return json.dumps(payload, default=str, separators=(",", ":"))


class RequestIdMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: Any, logger: logging.Logger | None = None) -> None:
        super().__init__(app)
        self._logger = logger or logging.getLogger("app.request")

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid4().hex
        request.state.request_id = request_id
        started_at = time.perf_counter()

        self._logger.info(
            "request_started",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
            },
        )

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
            self._logger.exception(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                },
            )
            raise

        duration_ms = round((time.perf_counter() - started_at) * 1000, 2)
        response.headers[REQUEST_ID_HEADER] = request_id
        self._logger.info(
            "request_finished",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response


def configure_logging(settings: Settings) -> None:
    level = logging.getLevelName(settings.log_level.upper())
    if not isinstance(level, int):
        level = logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers:
        if getattr(handler, "_knowledge_alakazam_json", False):
            handler.setLevel(level)
            handler.setFormatter(JsonLogFormatter())
            return

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(JsonLogFormatter())
    handler.__dict__["_knowledge_alakazam_json"] = True
    root_logger.addHandler(handler)


def _sanitize_log_value(key: str, value: Any) -> Any:
    lowered = key.lower()
    if any(marker in lowered for marker in _SECRET_FIELD_MARKERS):
        return "[redacted]"

    if isinstance(value, dict):
        return {
            str(item_key): _sanitize_log_value(str(item_key), item_value)
            for item_key, item_value in value.items()
        }

    if isinstance(value, (list, tuple)):
        return [_sanitize_log_value(key, item) for item in value]

    return value
