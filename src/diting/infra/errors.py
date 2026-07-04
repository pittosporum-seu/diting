"""谛听 · 异常层次结构"""


class DitingError(Exception):
    """谛听所有异常的基类"""
    pass


class DataUnavailableError(DitingError):
    """数据不可用"""
    pass


class AllProvidersFailedError(DataUnavailableError):
    """所有数据源均失败"""
    pass


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


class ConfigError(DitingError):
    """配置错误"""
    pass
