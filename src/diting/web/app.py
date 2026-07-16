"""谛听 · Web 服务 — FastAPI 应用

挂载静态文件、初始化 Jinja2 模板、注册路由。
包含全局异常处理器，统一所有端点错误响应格式。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import numpy as np
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..infra.errors import AnalysisError


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

app = FastAPI(title="谛听", version="0.7.0")
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
app.mount("/app", StaticFiles(directory=str(FRONTEND), html=True), name="frontend")
templates = Jinja2Templates(directory=str(TEMPLATES))

# ── v0.6.5: 启动后台预刷新 Worker ──
_prefetch_worker = None


@app.on_event("startup")
async def start_prefetch_worker():
    """启动后台预刷新线程。"""
    global _prefetch_worker
    try:
        from ..cache.prefetch import PrefetchWorker
        from .routes import stock_service as service
        _prefetch_worker = PrefetchWorker(service)
        _prefetch_worker.start()
    except Exception:
        import logging
        logging.getLogger(__name__).warning("prefetch.startup_failed")


@app.on_event("shutdown")
async def stop_prefetch_worker():
    """停止后台预刷新线程。"""
    global _prefetch_worker
    if _prefetch_worker is not None:
        _prefetch_worker.stop()


# ── 全局异常处理器 ──────────────────────────────────────────
# 统一所有 API 端点的错误响应格式为 ApiErrorResponse


@app.exception_handler(AnalysisError)
async def analysis_error_handler(request: Request, exc: AnalysisError) -> JSONResponse:
    """处理 AnalysisError 及其子类 → 返回统一 ApiErrorResponse。"""
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
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    """处理 Starlette HTTPException（含 404 等）→ 统一 ApiErrorResponse。"""
    error_code_map = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
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
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "内部服务器错误",
            "error_code": "INTERNAL_ERROR",
            "detail": str(exc),
            "request_id": str(uuid.uuid4()),
        },
    )


from .routes import router  # noqa: E402, I001
app.include_router(router)
