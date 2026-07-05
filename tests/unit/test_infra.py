"""infra 层测试：异常 + 装饰器"""


import pytest

from src.diting.infra.decorators import cached, log_latency, retry
from src.diting.infra.errors import (
    AllProvidersFailedError,
    ConfigError,
    DataUnavailableError,
    DitingError,
    EngineFailedError,
    PipelineError,
    SandboxError,
)


class TestErrors:
    def test_diting_error_base(self):
        with pytest.raises(DitingError):
            raise DitingError("test")

    def test_data_unavailable_is_diting_error(self):
        with pytest.raises(DitingError):
            raise DataUnavailableError()

    def test_all_providers_failed_is_data_unavailable(self):
        with pytest.raises(DataUnavailableError):
            raise AllProvidersFailedError()

    def test_engine_failed_has_attrs(self):
        e = EngineFailedError("wyckoff", "002475", "timeout")
        assert e.engine_name == "wyckoff"
        assert e.symbol == "002475"
        assert "timeout" in str(e)

    def test_sandbox_error_has_traceback(self):
        e = SandboxError("x = 1/0", "ZeroDivisionError: division by zero")
        assert "ZeroDivisionError" in e.traceback_msg
        assert "x = 1/0" in e.code_snippet

    def test_pipeline_error_has_step(self):
        e = PipelineError("fetch", "connection refused")
        assert e.step == "fetch"
        assert "connection refused" in str(e)

    def test_config_error(self):
        with pytest.raises(DitingError):
            raise ConfigError("missing API key")


class TestCachedDecorator:
    def test_cache_hit(self):
        call_count = 0

        @cached(ttl_seconds=60)
        def expensive():
            nonlocal call_count
            call_count += 1
            return call_count

        assert expensive() == 1
        assert expensive() == 1  # cached
        assert call_count == 1

    def test_cache_miss_different_args(self):
        @cached(ttl_seconds=60)
        def double(x):
            return x * 2

        assert double(2) == 4
        assert double(3) == 6


class TestRetryDecorator:
    def test_retry_success_first_attempt(self):
        call_count = 0

        @retry(max_attempts=3, backoff=0.01)
        def succeed():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeed() == "ok"
        assert call_count == 1

    def test_retry_exhausted(self):
        @retry(max_attempts=2, backoff=0.01, on=(ValueError,))
        def always_fail():
            raise ValueError("fail")

        with pytest.raises(ValueError):
            always_fail()


class TestLogLatencyDecorator:
    def test_log_latency_returns_value(self):
        @log_latency
        def fast():
            return 42

        assert fast() == 42
