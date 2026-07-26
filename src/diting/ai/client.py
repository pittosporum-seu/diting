"""谛听 · LiteLLM AI 客户端

统一 completion 接口，支持 100+ provider。
通过 model 字符串切换 provider（如 deepseek/deepseek-v4-pro, openai/gpt-4o）。
"""

from __future__ import annotations

import time
from typing import Any

from litellm import completion

from ..infra.errors import EngineFailedError
from ..infra.logging_config import get_logger

logger = get_logger(__name__)


class AIClient:
    """LiteLLM 封装，所有引擎通过此接口调用 AI。"""

    def __init__(
        self,
        model: str = "deepseek/deepseek-v4-pro",
        api_key: str = "",
        temperature: float = 0.3,
        max_tokens: int = 4000,
        api_base: str = "",
    ):
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.api_base = api_base

    def complete(
        self,
        system: str,
        user: str,
        **kwargs: Any,
    ) -> str:
        """发送 completion 请求。

        Args:
            system: system prompt
            user: user message
            **kwargs: 覆盖实例默认参数（temperature, max_tokens, model）

        Returns:
            AI 响应文本

        Raises:
            EngineFailedError: AI 调用失败
        """
        model = kwargs.pop("model", self.model)
        temperature = kwargs.pop("temperature", self.temperature)
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        api_base = kwargs.pop("api_base", self.api_base)

        start = time.perf_counter()
        try:
            response = completion(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
                api_key=self.api_key or None,
                api_base=api_base or None,
                **kwargs,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - start) * 1000
            logger.error(
                "ai.completion.failed",
                model=model,
                error=str(e),
                duration_ms=round(elapsed),
            )
            raise EngineFailedError(
                engine_name="ai",
                symbol="",
                reason=f"AI call failed ({model}): {e}",
            ) from e

        elapsed = (time.perf_counter() - start) * 1000
        content = response.choices[0].message.content or ""
        logger.info(
            "ai.completion.done",
            model=model,
            duration_ms=round(elapsed),
            response_len=len(content),
        )
        return content


# 模块级默认实例
_llm: AIClient | None = None


def get_llm() -> AIClient:
    """获取默认 LLM 实例，优先读 DB 设置，回退到环境变量。"""
    global _llm
    if _llm is None:
        import os

        api_key = os.environ.get("AI_API_KEY", "")
        default_model = os.environ.get("AI_MODEL", "deepseek/deepseek-v4-pro")
        api_base = os.environ.get("AI_BASE_URL", "")

        # 尝试从 DB 读取用户保存的模型 / base_url
        model = default_model
        try:
            from ..storage import WatchlistDB

            db = WatchlistDB()
            saved = db.get_settings()
            if saved.get("ai_model"):
                model = saved["ai_model"]
            if saved.get("ai_base_url"):
                api_base = saved["ai_base_url"]
        except Exception:
            pass

        _llm = AIClient(model=model, api_key=api_key, api_base=api_base)
    return _llm
