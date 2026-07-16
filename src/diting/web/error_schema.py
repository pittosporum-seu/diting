"""谛听 · Web 层 — 统一 API 错误响应协议

所有 API 错误端点返回一致格式的 ApiErrorResponse。
由全局异常处理器在 app.py 中统一构建。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ApiErrorResponse:
    """统一 API 错误响应格式。

    所有异常处理器返回此结构的 JSON，确保前端只需一套错误解析逻辑。
    """

    success: bool = False
    error: str = ""  # 人类可读的错误描述
    error_code: str = ""  # 机器可读的错误代码（如 "DATA_UNAVAILABLE"）
    detail: str | None = None  # 调试信息（生产环境可关闭）
    request_id: str | None = None  # 请求追踪 ID

    def to_dict(self) -> dict:
        """转为 JSON 可序列化的 dict。"""
        return {
            "success": self.success,
            "error": self.error,
            "error_code": self.error_code,
            "detail": self.detail,
            "request_id": self.request_id,
        }
