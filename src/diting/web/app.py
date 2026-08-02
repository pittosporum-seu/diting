"""FastAPI application factory for the Diting v0.8 HTTP surface."""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..bootstrap import ApplicationContainer, bootstrap_runtime
from ..infra.errors import AnalysisError
from .contracts_v1 import error_envelope
from .routes import build_router

os.environ.setdefault("LITELLM_LOG", "ERROR")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND = PROJECT_ROOT / "frontend"


def create_app(
    container: ApplicationContainer,
    *,
    frontend_dir: Path = FRONTEND,
) -> FastAPI:
    """Create one HTTP application from an already assembled dependency graph."""

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            container.close()

    application = FastAPI(
        title="谛听",
        version=__version__,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request.state.request_id = f"req_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(AnalysisError)
    async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
        message = str(exc) if exc.http_status_code < 500 else "服务暂时不可用"
        return _error_response(
            request,
            exc.http_status_code,
            exc.error_code,
            message,
            retryable=exc.http_status_code in {429, 502, 503, 504},
        )

    @application.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return _error_response(request, 400, "INVALID_PARAMETER", str(exc))

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        error_code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code,
            "HTTP_ERROR",
        )
        return _error_response(
            request,
            exc.status_code,
            error_code,
            str(exc.detail) if exc.detail else "请求失败",
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(request, 422, "VALIDATION_ERROR", "请求参数校验失败")

    @application.exception_handler(Exception)
    async def generic_exception_handler(request: Request, _exc: Exception) -> JSONResponse:
        return _error_response(request, 500, "INTERNAL_ERROR", "内部服务器错误")

    application.include_router(build_router(container, frontend_dir=frontend_dir))
    return application


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> JSONResponse:
    envelope = error_envelope(
        request,
        code=code,
        message=message,
        retryable=retryable,
    )
    return JSONResponse(status_code=status_code, content=envelope.model_dump(mode="json"))


container = bootstrap_runtime()
app = create_app(container)
