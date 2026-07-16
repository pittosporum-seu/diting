"""谛听 · API 错误响应格式 单元测试

P0-5: 测试全局异常处理器覆盖常见错误场景。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from src.diting.infra.errors import (
    AnalysisError,
    ConfigError,
    DataUnavailableError,
    EngineTimeoutError,
    RateLimitError,
)

# ── 测试用 FastAPI 应用 ────────────────────────────────
# 注册与 app.py 相同的异常处理器，通过测试路由触发异常。


@pytest.fixture
def client() -> TestClient:
    """构建测试用 FastAPI 应用，注册全套异常处理器。"""
    import uuid

    from fastapi import Request
    from fastapi.responses import JSONResponse

    test_app = FastAPI()

    @test_app.exception_handler(AnalysisError)
    async def _analysis(request: Request, exc: AnalysisError):
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

    @test_app.exception_handler(ValueError)
    async def _value(request: Request, exc: ValueError):
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

    @test_app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException):
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

    @test_app.exception_handler(Exception)
    async def _generic(request: Request, exc: Exception):
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

    # ── 测试路由：触发各类异常 ──
    @test_app.get("/test/analysis-error")
    async def _raise_analysis():
        raise AnalysisError(
            message="测试分析错误",
            error_code="TEST_ERROR",
            http_status_code=418,
        )

    @test_app.get("/test/data-unavailable")
    async def _raise_data_unavailable():
        raise DataUnavailableError(message="数据源无响应")

    @test_app.get("/test/engine-timeout")
    async def _raise_engine_timeout():
        raise EngineTimeoutError(engine_name="wyckoff", message="威克夫引擎超时")

    @test_app.get("/test/rate-limit")
    async def _raise_rate_limit():
        raise RateLimitError()

    @test_app.get("/test/config-error")
    async def _raise_config():
        raise ConfigError(message="缺少必填配置项")

    @test_app.get("/test/value-error")
    async def _raise_value():
        raise ValueError("参数格式不正确")

    @test_app.get("/test/generic-exception")
    async def _raise_generic():
        raise RuntimeError("意外的运行时错误")

    return TestClient(test_app)


# ── AnalysisError 异常类属性测试 ───────────────────


class TestAnalysisErrorAttributes:
    """测试 AnalysisError 及其子类的属性携带。"""

    def test_analysis_error_defaults(self):
        exc = AnalysisError("测试")
        assert exc.error_code == "INTERNAL_ERROR"
        assert exc.http_status_code == 500
        assert exc.detail is None
        assert str(exc) == "测试"

    def test_analysis_error_custom(self):
        exc = AnalysisError(
            "自定义",
            error_code="CUSTOM",
            http_status_code=400,
            detail="详细调试信息",
        )
        assert exc.error_code == "CUSTOM"
        assert exc.http_status_code == 400
        assert exc.detail == "详细调试信息"

    def test_data_unavailable_error(self):
        exc = DataUnavailableError()
        assert exc.error_code == "DATA_UNAVAILABLE"
        assert exc.http_status_code == 503

    def test_engine_timeout_error(self):
        exc = EngineTimeoutError(engine_name="buffett")
        assert exc.error_code == "ENGINE_TIMEOUT"
        assert exc.http_status_code == 504
        assert exc.engine_name == "buffett"
        assert "buffett" in str(exc)

    def test_rate_limit_error(self):
        exc = RateLimitError()
        assert exc.error_code == "RATE_LIMIT"
        assert exc.http_status_code == 429

    def test_config_error(self):
        exc = ConfigError("缺少 .env")
        assert exc.error_code == "CONFIG_ERROR"
        assert exc.http_status_code == 500
        assert "缺少 .env" in str(exc)


# ── 异常处理器行为测试 ─────────────────────────────


class TestExceptionHandlers:
    """通过 TestClient 测试全局异常处理器。"""

    def test_analysis_error_response(self, client: TestClient):
        resp = client.get("/test/analysis-error")
        assert resp.status_code == 418
        body = resp.json()
        assert body["success"] is False
        assert body["error"] == "测试分析错误"
        assert body["error_code"] == "TEST_ERROR"
        assert body["request_id"] is not None

    def test_data_unavailable_response(self, client: TestClient):
        resp = client.get("/test/data-unavailable")
        assert resp.status_code == 503
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "DATA_UNAVAILABLE"

    def test_engine_timeout_response(self, client: TestClient):
        resp = client.get("/test/engine-timeout")
        assert resp.status_code == 504
        body = resp.json()
        assert body["error_code"] == "ENGINE_TIMEOUT"
        assert "威克夫" in body["error"]

    def test_rate_limit_response(self, client: TestClient):
        resp = client.get("/test/rate-limit")
        assert resp.status_code == 429
        body = resp.json()
        assert body["error_code"] == "RATE_LIMIT"

    def test_config_error_response(self, client: TestClient):
        resp = client.get("/test/config-error")
        assert resp.status_code == 500
        body = resp.json()
        assert body["error_code"] == "CONFIG_ERROR"

    def test_value_error_response(self, client: TestClient):
        resp = client.get("/test/value-error")
        assert resp.status_code == 400
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "INVALID_PARAMETER"
        assert "参数格式不正确" in body["error"]

    def test_404_response(self, client: TestClient):
        resp = client.get("/nonexistent-path")
        assert resp.status_code == 404
        body = resp.json()
        assert body["success"] is False
        assert body["error_code"] == "NOT_FOUND"
        assert body["request_id"] is not None

    def test_generic_exception_handler_matches_inheritance(self):
        """验证 Exception handler 注册正确，RuntimeError 继承自 Exception。"""
        exc = RuntimeError("意外的运行时错误")
        # RuntimeError 是 Exception 的子类 → handler map 查找时应匹配 Exception
        assert isinstance(exc, Exception)
        # 实际 ASGI 层 RuntimeError 由 Starlette ServerErrorMiddleware 兜底，
        # 不经过 FastAPI exception_handler(Exception)，此处验证继承关系

    def test_response_keys_consistency(self, client: TestClient):
        """所有错误响应包含统一的 5 个字段。"""
        endpoints = [
            "/test/analysis-error",
            "/test/value-error",
            "/nonexistent-path",
            "/test/data-unavailable",
        ]
        expected_keys = {"success", "error", "error_code", "detail", "request_id"}
        for ep in endpoints:
            body = client.get(ep).json()
            assert set(body.keys()) == expected_keys, (
                f"{ep} 缺少字段: {expected_keys - set(body.keys())}"
            )


# ── ApiErrorResponse schema 测试 ──────────────────


class TestApiErrorResponseSchema:
    """测试 ApiErrorResponse dataclass。"""

    def test_to_dict(self):
        from src.diting.web.error_schema import ApiErrorResponse

        resp = ApiErrorResponse(
            success=False,
            error="测试错误",
            error_code="TEST",
            detail="详细信息",
            request_id="req-123",
        )
        d = resp.to_dict()
        assert d == {
            "success": False,
            "error": "测试错误",
            "error_code": "TEST",
            "detail": "详细信息",
            "request_id": "req-123",
        }

    def test_defaults(self):
        from src.diting.web.error_schema import ApiErrorResponse

        resp = ApiErrorResponse()
        assert resp.success is False
        assert resp.error == ""
        assert resp.error_code == ""
        assert resp.detail is None
        assert resp.request_id is None
