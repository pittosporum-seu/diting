"""谛听 · Python 沙箱执行器

基于 sandboxmcp 封装，提供安全隔离的计算环境。
AI 生成的计算代码在沙箱中执行，避免幻觉输出。
"""

from __future__ import annotations

from ..infra.errors import SandboxError
from ..infra.logging_config import get_logger

logger = get_logger(__name__)


class SandboxExecutor:
    """Python 沙箱执行器 — sandboxmcp 封装。

    process 后端：seccomp + namespace 隔离，零额外依赖。
    """

    def __init__(
        self,
        backend: str = "process",
        memory_limit_mb: int = 512,
        timeout_seconds: int = 60,
    ):
        self._backend = backend
        self._memory_limit_mb = memory_limit_mb
        self._timeout_seconds = timeout_seconds
        self._sandbox = None

    def _get_sandbox(self):
        if self._sandbox is None:
            from sandboxmcp import Sandbox

            self._sandbox = Sandbox(
                backend=self._backend,
                memory_limit_mb=self._memory_limit_mb,
                timeout_seconds=self._timeout_seconds,
                network_enabled=False,
            )
        return self._sandbox

    def run(self, code: str) -> dict:
        """在沙箱中执行 Python 代码。

        Args:
            code: AI 生成的 Python 代码

        Returns:
            {"output": str, "errors": list, "execution_time_ms": int}

        Raises:
            SandboxError: 沙箱不可用或执行失败
        """
        try:
            sandbox = self._get_sandbox()
            result = sandbox.run(code)
        except Exception as e:
            logger.error("sandbox.failed", error=str(e))
            raise SandboxError(code[:200], str(e)) from e

        logger.info(
            "sandbox.executed",
            code_len=len(code),
            has_errors=bool(result.get("errors")),
        )
        return result

    def run_with_retry(
        self, code: str, fix_prompt: str, llm, max_retries: int = 1
    ) -> dict:
        """执行代码，失败时 AI 自动修复重试。

        Args:
            code: 初始代码
            fix_prompt: 用于 AI 修复的 system prompt
            llm: AIClient 实例
            max_retries: 最大重试次数

        Returns:
            沙箱执行结果
        """
        for attempt in range(max_retries + 1):
            result = self.run(code)
            errors = result.get("errors", [])

            if not errors:
                return result

            if attempt < max_retries:
                logger.warning(
                    "sandbox.retrying",
                    attempt=attempt + 1,
                    error=str(errors)[:200],
                )
                # AI 修复
                code = llm.complete(
                    system=fix_prompt,
                    user=f"Code that failed:\n```python\n{code}\n```\n\n"
                         f"Errors:\n{errors}\n\nFix the code.",
                )
                # 提取代码块
                if "```python" in code:
                    code = code.split("```python")[1].split("```")[0]
                elif "```" in code:
                    code = code.split("```")[1].split("```")[0]

        return result


# 模块级默认实例
_sandbox: SandboxExecutor | None = None


def get_sandbox() -> SandboxExecutor:
    global _sandbox
    if _sandbox is None:
        _sandbox = SandboxExecutor()
    return _sandbox
