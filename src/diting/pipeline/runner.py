"""谛听 · 分析管道编排器"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from ..engines.registry import discover_engines, get_engine
from ..infra.config_loader import ConfigLoader
from ..infra.logging_config import get_logger
from ..schema import AnalysisContext, AnalysisResult, PipelineResult

logger = get_logger(__name__)


class AnalysisPipeline:
    """分析管道——并行执行引擎 + 错误不阻塞 + 单引擎超时 25s"""

    _ENGINE_TIMEOUT = 25  # v0.6.6: 每个引擎超时秒数

    def __init__(self, engine_names: list[str] | None = None):
        self._engine_names = engine_names or discover_engines()
        pipe_cfg = ConfigLoader.get_section("pipeline")
        self._max_workers = pipe_cfg.get("max_workers", 4)

    def run(self, contexts: list[AnalysisContext]) -> PipelineResult:
        """对多只股票的多个引擎并行分析。

        一个引擎失败/超时不阻塞其他引擎。
        """
        start = datetime.now()
        results: dict[str, list[AnalysisResult]] = {}
        errors: list[dict] = []

        for ctx in contexts:
            engine_results: list[AnalysisResult] = []
            with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
                futures = {
                    pool.submit(self._run_engine, name, ctx): name for name in self._engine_names
                }
                for future in as_completed(futures):
                    ename = futures[future]
                    try:
                        result = future.result(timeout=self._ENGINE_TIMEOUT)
                        engine_results.append(result)
                    except TimeoutError:
                        logger.warning(
                            "pipeline.engine_timeout",
                            engine=ename,
                            symbol=ctx.symbol,
                            timeout_s=self._ENGINE_TIMEOUT,
                        )
                        errors.append(
                            {
                                "engine": ename,
                                "symbol": ctx.symbol,
                                "error": f"Engine {ename} timed out after {self._ENGINE_TIMEOUT}s",
                            }
                        )
                    except Exception as e:
                        logger.warning("pipeline.engine_failed", engine=ename, error=str(e))
                        errors.append({"engine": ename, "symbol": ctx.symbol, "error": str(e)})

            results[ctx.symbol] = engine_results

        duration = int((datetime.now() - start).total_seconds() * 1000)
        return PipelineResult(
            symbols=(
                tuple([contexts[0].symbol])
                if len(contexts) == 1
                else tuple(c.symbol for c in contexts)
            ),
            results=results,
            errors=tuple(errors),
            metrics={
                "duration_ms": duration,
                "engines": len(self._engine_names),
                "symbols": len(contexts),
            },
        )

    @staticmethod
    def _run_engine(name: str, ctx: AnalysisContext) -> AnalysisResult:
        engine_cls = get_engine(name)
        if engine_cls is None:
            raise ValueError(f"Engine not found: {name}")
        engine = engine_cls()
        if not engine.validate_context(ctx):
            logger.info("pipeline.context_invalid", engine=name, symbol=ctx.symbol)
        return engine.analyze(ctx)
