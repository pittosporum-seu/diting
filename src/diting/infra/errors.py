"""谛听 · 异常层次结构

统一的异常体系，分为两层：
- DitingError：所有谛听异常的根
- AnalysisError：API 级别的分析错误，携带 error_code 和 http_status_code
"""

from __future__ import annotations


class DitingError(Exception):
    """谛听所有异常的基类"""

    pass


class AnalysisError(DitingError):
    """API 级别的分析错误基类。

    所有需要通过 API 返回给客户端的错误应继承此类。
    携带机器可读的 error_code 和 HTTP 状态码，
    由全局异常处理器统一转换为 ApiErrorResponse。
    """

    def __init__(
        self,
        message: str = "",
        *,
        error_code: str = "INTERNAL_ERROR",
        http_status_code: int = 500,
        detail: str | None = None,
    ):
        self.error_code = error_code
        self.http_status_code = http_status_code
        self.detail = detail
        super().__init__(message)


class DataUnavailableError(AnalysisError):
    """数据不可用 — 上游数据源返回空或查询失败"""

    def __init__(
        self,
        message: str = "数据不可用",
        *,
        error_code: str = "DATA_UNAVAILABLE",
        http_status_code: int = 503,
        detail: str | None = None,
    ):
        super().__init__(
            message,
            error_code=error_code,
            http_status_code=http_status_code,
            detail=detail,
        )


class AllProvidersFailedError(DataUnavailableError):
    """所有数据源均失败"""

    def __init__(self, message: str = "所有数据源均失败"):
        super().__init__(message)


class ProviderTransientError(DataUnavailableError):
    """A retryable upstream failure such as timeout or temporary rate limiting."""


class ProviderNotFoundError(DataUnavailableError):
    """The requested instrument or dataset definitively does not exist."""

    def __init__(self, message: str = "证券或数据不存在"):
        super().__init__(message, error_code="NOT_FOUND", http_status_code=404)


class EngineTimeoutError(AnalysisError):
    """分析引擎执行超时"""

    def __init__(
        self,
        engine_name: str = "",
        message: str = "",
        *,
        error_code: str = "ENGINE_TIMEOUT",
        http_status_code: int = 504,
        detail: str | None = None,
    ):
        self.engine_name = engine_name
        msg = message or f"引擎 [{engine_name}] 执行超时"
        super().__init__(
            msg,
            error_code=error_code,
            http_status_code=http_status_code,
            detail=detail,
        )


class RateLimitError(AnalysisError):
    """请求频率限制"""

    def __init__(
        self,
        message: str = "请求过于频繁，请稍后重试",
        *,
        error_code: str = "RATE_LIMIT",
        http_status_code: int = 429,
        detail: str | None = None,
    ):
        super().__init__(
            message,
            error_code=error_code,
            http_status_code=http_status_code,
            detail=detail,
        )


class ConfigError(AnalysisError):
    """配置错误"""

    def __init__(
        self,
        message: str = "配置错误",
        *,
        error_code: str = "CONFIG_ERROR",
        http_status_code: int = 500,
        detail: str | None = None,
    ):
        super().__init__(
            message,
            error_code=error_code,
            http_status_code=http_status_code,
            detail=detail,
        )


class MigrationError(DitingError):
    """A database migration failed or its recorded checksum changed."""

    def __init__(self, database: str, reason: str):
        self.database = database
        self.reason = reason
        super().__init__(f"Migration failed for {database}: {reason}")


class EngineFailedError(DitingError):
    """分析引擎执行失败"""

    def __init__(self, engine_name: str, symbol: str, reason: str):
        self.engine_name = engine_name
        self.symbol = symbol
        self.reason = reason
        super().__init__(f"[{engine_name}] {symbol}: {reason}")


class SandboxError(DitingError):
    """沙箱执行失败"""

    def __init__(self, code_snippet: str, traceback_msg: str):
        self.code_snippet = code_snippet[:200]
        self.traceback_msg = traceback_msg
        super().__init__(f"Sandbox failed: {traceback_msg[:200]}")


class PipelineError(DitingError):
    """管道执行错误"""

    def __init__(self, step: str, message: str):
        self.step = step
        self.message = message
        super().__init__(f"[{step}] {message}")
