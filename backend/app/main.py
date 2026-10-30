import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes import router
from app.core.config import get_settings
from app.core.db import dispose_engine
from app.core.errors import AppError
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.schemas.common import ErrorDetail, ErrorEnvelope

logger = logging.getLogger(__name__)
_SENSITIVE_FIELD_PARTS = ("api_key", "password", "secret", "access_token")


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _redact_sensitive_validation_input(value: object, *, field_name: str = "") -> object:
    """Keep validation diagnostics useful without reflecting submitted credentials."""

    lowered = field_name.lower()
    if any(part in lowered for part in _SENSITIVE_FIELD_PARTS):
        return "[REDACTED]"
    if isinstance(value, dict):
        location = value.get("loc")
        sensitive_location = isinstance(location, (list, tuple)) and any(
            any(part in str(segment).lower() for part in _SENSITIVE_FIELD_PARTS)
            for segment in location
        )
        return {
            key: (
                "[REDACTED]"
                if sensitive_location and key == "input"
                else _redact_sensitive_validation_input(item, field_name=str(key))
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_validation_input(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_validation_input(item) for item in value)
    return value


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    body = ErrorEnvelope(
        error=ErrorDetail(code=code, message=message, details=details or {}),
        request_id=_request_id(request),
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(body))


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="IndusOpt API",
        version=settings.app_version,
        description=(
            "IndusOpt 工模智优 API：工业时序数据管理、动态优选、系统辨识、闭环优化、Agent 执行及可追溯报告与数据交付。"
        ),
        openapi_version="3.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(
            "application_error",
            extra={"error_code": exc.code, "status_code": exc.status_code},
        )
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _error_response(
            request,
            status_code=422,
            code="REQUEST_VALIDATION_FAILED",
            message="请求参数校验失败",
            details={
                "issues": jsonable_encoder(_redact_sensitive_validation_input(exc.errors()))
            },
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = "ROUTE_NOT_FOUND" if exc.status_code == 404 else "HTTP_ERROR"
        message = "接口不存在" if exc.status_code == 404 else "请求无法处理"
        return _error_response(
            request,
            status_code=exc.status_code,
            code=code,
            message=message,
            details={"detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_exception")
        return _error_response(
            request,
            status_code=500,
            code="SYSTEM_INTERNAL_ERROR",
            message="系统内部错误",
        )

    app.include_router(router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
