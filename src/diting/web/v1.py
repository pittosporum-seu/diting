"""Public read-only HTTP v1 routes backed by v0.8 application ports."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request

from .. import __version__
from ..bootstrap import ApplicationContainer
from ..infra.errors import DataUnavailableError
from ..schema import (
    AnalysisRun,
    InstrumentSearchRequest,
    OwnerSession,
    QuoteRequest,
)
from .contracts_v1 import (
    AnalysisRunView,
    ApiEnvelope,
    ConsensusView,
    DashboardData,
    EngineRunView,
    HealthData,
    InstrumentSearchData,
    InstrumentView,
    OpportunitiesData,
    QuoteData,
    VerdictView,
    WarningInfo,
    data_result_meta,
    success_envelope,
)
from .security import OwnerSecurity


def build_v1_router(container: ApplicationContainer) -> APIRouter:
    if container.auth is None or container.data_gateway is None or container.durable_store is None:
        raise RuntimeError("v1 runtime dependencies are incomplete")
    router = APIRouter(prefix="/api/v1", tags=["v1"])
    security = OwnerSecurity(container.auth, container.settings)

    @router.get("/health", response_model=ApiEnvelope[HealthData])
    async def health(request: Request):
        return success_envelope(request, HealthData(status="ok", version=__version__))

    @router.get("/ready", response_model=ApiEnvelope[HealthData])
    async def ready(request: Request):
        return success_envelope(request, HealthData(status="ready", version=__version__))

    @router.get(
        "/instruments/search",
        response_model=ApiEnvelope[InstrumentSearchData],
    )
    async def search_instruments(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=80)],
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        cursor: Annotated[str | None, Query(max_length=200)] = None,
        _access: OwnerSession | None = Depends(security.require_read_access),
    ):
        result = container.data_gateway.search_instruments(
            InstrumentSearchRequest(query=q, limit=limit, cursor=cursor)
        )
        if not result.succeeded or result.data is None:
            raise DataUnavailableError(
                "证券目录暂时不可用",
                error_code=result.error_code or "DATA_UNAVAILABLE",
            )
        data = InstrumentSearchData(
            items=tuple(
                InstrumentView(
                    symbol=item.symbol,
                    name=item.name,
                    market=item.market,
                    instrument_type=item.instrument_type,
                    listed_on=item.listed_on.isoformat() if item.listed_on else None,
                    delisted_on=item.delisted_on.isoformat() if item.delisted_on else None,
                )
                for item in result.data.items
            ),
            total=result.data.total,
            next_cursor=result.data.next_cursor,
        )
        cache, freshness, warnings = data_result_meta(result)
        return success_envelope(
            request,
            data,
            cache=cache,
            freshness=freshness,
            warnings=warnings,
        )

    @router.get("/stocks/{symbol}", response_model=ApiEnvelope[QuoteData])
    async def get_stock(
        request: Request,
        symbol: Annotated[str, Path(pattern=r"^\d{6}$")],
        _access: OwnerSession | None = Depends(security.require_read_access),
    ):
        result = container.data_gateway.get_quotes(QuoteRequest(symbols=(symbol,))).get(symbol)
        if result is None or not result.succeeded or result.data is None:
            raise DataUnavailableError(
                "行情暂时不可用",
                error_code=result.error_code if result else "DATA_UNAVAILABLE",
            )
        quote = result.data
        data = QuoteData(
            symbol=quote.symbol,
            name=quote.name,
            price=quote.price,
            change_pct=quote.change_pct,
            open=quote.open,
            high=quote.high,
            low=quote.low,
            volume=quote.volume,
            turnover=quote.turnover,
            pe=quote.pe,
            pb=quote.pb,
            total_mv=quote.total_mv,
            timestamp=quote.timestamp,
            source=quote.source.value,
        )
        cache, freshness, warnings = data_result_meta(result)
        return success_envelope(
            request,
            data,
            result_status="partial" if warnings else "succeeded",
            cache=cache,
            freshness=freshness,
            warnings=warnings,
        )

    @router.get(
        "/analyses/{run_id}",
        response_model=ApiEnvelope[AnalysisRunView],
    )
    async def get_analysis(
        request: Request,
        run_id: Annotated[str, Path(pattern=r"^run_[A-Za-z0-9_-]+$")],
        _access: OwnerSession | None = Depends(security.require_read_access),
    ):
        run = container.durable_store.get_analysis_run(run_id)
        if run is None:
            from ..infra.errors import AnalysisError

            raise AnalysisError(
                "分析结果不存在",
                error_code="ANALYSIS_NOT_FOUND",
                http_status_code=404,
            )
        return success_envelope(request, _analysis_view(run), result_status=run.status.value)

    @router.get("/dashboard", response_model=ApiEnvelope[DashboardData])
    async def dashboard(
        request: Request,
        _access: OwnerSession | None = Depends(security.require_read_access),
    ):
        active = container.durable_store.get_active_strategy(container.settings.strategy.selected)
        return success_envelope(
            request,
            DashboardData(
                version=__version__,
                analysis_available=container.analysis is not None,
                active_strategy=f"{active.name}:{active.version}" if active else None,
                public_readonly=container.settings.runtime.public_readonly,
            ),
        )

    @router.get("/opportunities", response_model=ApiEnvelope[OpportunitiesData])
    async def opportunities(
        request: Request,
        _access: OwnerSession | None = Depends(security.require_read_access),
    ):
        active = container.durable_store.get_active_strategy(container.settings.strategy.selected)
        if active is None:
            return success_envelope(
                request,
                OpportunitiesData(),
                result_status="unavailable",
                warnings=(
                    WarningInfo(
                        code="NO_ACTIVE_STRATEGY",
                        message="当前没有已激活的生产机会策略",
                        recoverable=True,
                    ),
                ),
            )
        return success_envelope(
            request,
            OpportunitiesData(strategy_version=f"{active.name}:{active.version}"),
        )

    return router


def _analysis_view(run: AnalysisRun) -> AnalysisRunView:
    consensus = None
    if run.consensus is not None:
        consensus = ConsensusView(
            analysis_score=run.consensus.analysis_score,
            confidence=run.consensus.confidence,
            weight_coverage=run.consensus.weight_coverage,
            engines_used=run.consensus.engines_used,
            engines_failed=run.consensus.engines_failed,
            insufficient_reason=run.consensus.insufficient_reason,
        )
    verdict = None
    if run.verdict is not None:
        verdict = VerdictView(
            label=run.verdict.label.value,
            horizon=run.verdict.horizon,
            summary=run.verdict.summary,
            confidence=run.verdict.confidence,
        )
    return AnalysisRunView(
        run_id=run.run_id,
        symbol=run.symbol,
        profile=run.profile.value,
        status=run.status.value,
        snapshot_id=run.snapshot_id,
        snapshot_hash=run.snapshot_hash,
        config_hash=run.config_hash,
        strategy_version=run.strategy_version,
        code_version=run.code_version,
        started_at=run.started_at,
        completed_at=run.completed_at,
        engine_runs=tuple(
            EngineRunView(
                engine_name=item.engine_name,
                engine_version=item.engine_version,
                status=item.status.value,
                deterministic=item.deterministic,
                engine_score=item.engine_score,
                confidence=item.confidence,
                error_code=item.error_code,
                duration_ms=item.duration_ms,
            )
            for item in run.engine_runs
        ),
        consensus=consensus,
        verdict=verdict,
    )
