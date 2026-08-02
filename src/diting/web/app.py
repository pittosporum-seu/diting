"""谛听 · Web 服务 — FastAPI 应用

挂载静态文件、初始化 Jinja2 模板、注册路由。
包含全局异常处理器，统一所有端点错误响应格式。
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from .. import __version__
from ..infra.errors import AnalysisError
from .contracts_v1 import error_envelope


class NumpyEncoder(json.JSONEncoder):
    """Handle numpy types in JSON serialization."""

    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
        return super().default(obj)


# ── suppress LiteLLM debug noise ──
os.environ.setdefault("LITELLM_LOG", "ERROR")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
TEMPLATES = Path(__file__).resolve().parent / "templates"
STATIC = Path(__file__).resolve().parent / "static"
FRONTEND = PROJECT_ROOT / "frontend"

# ── v0.6.5: 启动后台预刷新 Worker ──
_prefetch_worker = None
_analysis_prefetch_worker = None


def start_prefetch_worker() -> None:
    """启动后台预刷新线程。"""
    global _prefetch_worker, _analysis_prefetch_worker
    try:
        from ..cache.prefetch import PrefetchWorker
        from .routes import stock_service as service

        _prefetch_worker = PrefetchWorker(service)
        _prefetch_worker.start()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("prefetch.startup_failed")
    # v0.7.5: 后台优先级个股抓取
    try:
        from ..cache.analysis_prefetch import AnalysisPrefetchWorker
        from .routes import dashboard_service, scan_service, stock_service

        _analysis_prefetch_worker = AnalysisPrefetchWorker(
            stock_service, scan_service, dashboard_service=dashboard_service
        )
        _analysis_prefetch_worker.start()
    except Exception:
        import logging

        logging.getLogger(__name__).warning("analysis_prefetch.startup_failed")


def stop_prefetch_worker() -> None:
    """停止后台预刷新线程。"""
    global _prefetch_worker, _analysis_prefetch_worker
    if _prefetch_worker is not None:
        _prefetch_worker.stop()
    if _analysis_prefetch_worker is not None:
        _analysis_prefetch_worker.stop()
    container.close()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Own worker and application-container resources for the process lifetime."""

    start_prefetch_worker()
    try:
        yield
    finally:
        stop_prefetch_worker()


app = FastAPI(title="谛听", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/app", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
templates = Jinja2Templates(directory=str(TEMPLATES))


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request.state.request_id = f"req_{uuid.uuid4().hex}"
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    return response


# ── 全局异常处理器 ──────────────────────────────────────────
# 统一所有 API 端点的错误响应格式为 ApiErrorResponse


@app.exception_handler(AnalysisError)
async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
    """处理 AnalysisError 及其子类 → 返回统一 ApiErrorResponse。"""
    if request.url.path.startswith("/api/v1/"):
        message = str(exc) if exc.http_status_code < 500 else "服务暂时不可用"
        return _v1_error_response(
            request,
            exc.http_status_code,
            exc.error_code,
            message,
            retryable=exc.http_status_code in {429, 502, 503, 504},
        )
    return JSONResponse(
        status_code=exc.http_status_code,
        content={
            "success": False,
            "error": str(exc),
            "error_code": exc.error_code,
            "detail": exc.detail,
            "request_id": str(uuid.uuid4()),
        },
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """处理 ValueError（参数校验失败）→ 400 Bad Request。"""
    if request.url.path.startswith("/api/v1/"):
        return _v1_error_response(request, 400, "INVALID_PARAMETER", str(exc))
    return JSONResponse(
        status_code=400,
        content={
            "success": False,
            "error": str(exc),
            "error_code": "INVALID_PARAMETER",
            "detail": None,
            "request_id": str(uuid.uuid4()),
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """处理 Starlette HTTPException（含 404 等）→ 统一 ApiErrorResponse。"""
    error_code_map = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    if request.url.path.startswith("/api/v1/"):
        return _v1_error_response(
            request,
            exc.status_code,
            error_code_map.get(exc.status_code, "HTTP_ERROR"),
            str(exc.detail) if exc.detail else "请求失败",
        )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "error": str(exc.detail) if exc.detail else "",
            "error_code": error_code_map.get(exc.status_code, "HTTP_ERROR"),
            "detail": None,
            "request_id": str(uuid.uuid4()),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底异常处理器 → 500 Internal Server Error。"""
    if request.url.path.startswith("/api/v1/"):
        return _v1_error_response(request, 500, "INTERNAL_ERROR", "内部服务器错误")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "内部服务器错误",
            "error_code": "INTERNAL_ERROR",
            "detail": None,
            "request_id": str(uuid.uuid4()),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    if request.url.path.startswith("/api/v1/"):
        return _v1_error_response(request, 422, "VALIDATION_ERROR", "请求参数校验失败")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "请求参数校验失败",
            "error_code": "VALIDATION_ERROR",
            "detail": None,
            "request_id": str(uuid.uuid4()),
        },
    )


def _v1_error_response(
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


from .routes import container, router  # noqa: E402, I001

app.include_router(router)
