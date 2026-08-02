"""Owner-only HTTP v1 operations with session, CSRF and audit controls."""

from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import __version__
from ..application.strategy_registry import StrategyRegistry
from ..bootstrap import ApplicationContainer
from ..enums import AnalysisProfile
from ..infra.errors import AnalysisError
from ..schema import (
    AnalysisRequest,
    AuditEvent,
    JobRecord,
    OwnerSession,
    PreferenceRecord,
    WatchlistEntry,
)
from .contracts_v1 import (
    ApiEnvelope,
    CacheClearData,
    DiagnosticsData,
    JobView,
    PreferencesData,
    PreferenceView,
    StrategyStatusData,
    WatchlistData,
    WatchlistView,
    request_id,
    success_envelope,
)
from .rate_limit import SlidingWindowRateLimiter
from .security import OwnerSecurity

OWNER_ID = "owner"


class _RequestModel(BaseModel):
    # JSON arrays and enum strings are their canonical wire forms.  Keep the
    # boundary closed to unknown fields without rejecting those valid forms.
    model_config = ConfigDict(extra="forbid")


class AnalysisCreateRequest(_RequestModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    profile: AnalysisProfile = AnalysisProfile.STANDARD
    force_refresh: bool = False
    requested_engines: tuple[str, ...] | None = None
    deadline_seconds: int = Field(default=300, ge=30, le=900)


class WatchlistUpsertRequest(_RequestModel):
    symbol: str = Field(pattern=r"^\d{6}$")
    name: str = Field(default="", max_length=80)
    market: Literal["SH", "SZ", "BJ"]
    tags: tuple[str, ...] = Field(default=(), max_length=20)


class PreferenceUpdateRequest(_RequestModel):
    key: Literal["theme", "default_profile", "page_size"]
    value: str | int | bool


class CacheClearRequest(_RequestModel):
    prefix: str | None = Field(default=None, max_length=160)


def build_owner_v1_router(
    container: ApplicationContainer,
    limiter: SlidingWindowRateLimiter | None = None,
) -> APIRouter:
    """Build owner endpoints only when all required v0.8 ports exist."""

    if container.auth is None or container.durable_store is None:
        raise RuntimeError("owner v1 runtime dependencies are incomplete")
    router = APIRouter(prefix="/api/v1", tags=["owner-v1"])
    security = OwnerSecurity(container.auth, container.settings)
    store = container.durable_store
    strategy_registry = StrategyRegistry(store, container.clock)

    @router.post("/analyses", response_model=ApiEnvelope[JobView], status_code=202)
    async def create_analysis(
        request: Request,
        body: AnalysisCreateRequest,
        session: OwnerSession = Depends(security.require_owner_write),
    ) -> JSONResponse:
        if container.jobs is None or container.analysis is None:
            raise AnalysisError(
                "分析任务服务不可用",
                error_code="ANALYSIS_SERVICE_UNAVAILABLE",
                http_status_code=503,
            )
        if limiter is not None:
            limiter.check_analysis(session)
        analysis_request = AnalysisRequest(
            symbol=body.symbol,
            profile=body.profile,
            force_refresh=body.force_refresh,
            requested_engines=body.requested_engines,
            request_id=request_id(request),
            deadline=container.clock.now() + timedelta(seconds=body.deadline_seconds),
        )
        job = container.jobs.submit_analysis(container.analysis, analysis_request)
        _audit(container, session, request, "analysis.create", job.job_id, {"symbol": body.symbol})
        envelope = success_envelope(request, _job_view(job), result_status=job.status.value)
        return JSONResponse(status_code=202, content=envelope.model_dump(mode="json"))

    @router.get("/jobs/{job_id}", response_model=ApiEnvelope[JobView])
    async def get_job(
        request: Request,
        job_id: Annotated[str, Path(pattern=r"^job_[A-Za-z0-9_-]+$")],
        _session: OwnerSession = Depends(security.require_owner),
    ):
        if container.jobs is None:
            raise AnalysisError(
                "任务服务不可用",
                error_code="JOB_SERVICE_UNAVAILABLE",
                http_status_code=503,
            )
        job = container.jobs.get(job_id)
        if job is None:
            raise AnalysisError("任务不存在", error_code="JOB_NOT_FOUND", http_status_code=404)
        return success_envelope(request, _job_view(job), result_status=job.status.value)

    @router.delete("/jobs/{job_id}", response_model=ApiEnvelope[JobView])
    async def cancel_job(
        request: Request,
        job_id: Annotated[str, Path(pattern=r"^job_[A-Za-z0-9_-]+$")],
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        if container.jobs is None:
            raise AnalysisError(
                "任务服务不可用",
                error_code="JOB_SERVICE_UNAVAILABLE",
                http_status_code=503,
            )
        job = container.jobs.cancel(job_id)
        if job is None:
            raise AnalysisError("任务不存在", error_code="JOB_NOT_FOUND", http_status_code=404)
        _audit(container, session, request, "job.cancel", job_id)
        return success_envelope(request, _job_view(job), result_status=job.status.value)

    @router.get("/watchlist", response_model=ApiEnvelope[WatchlistData])
    async def get_watchlist(
        request: Request,
        _session: OwnerSession = Depends(security.require_owner),
    ):
        items = tuple(_watchlist_view(item) for item in store.list_watchlist(OWNER_ID))
        return success_envelope(request, WatchlistData(items=items, total=len(items)))

    @router.post("/watchlist", response_model=ApiEnvelope[WatchlistView])
    async def upsert_watchlist(
        request: Request,
        body: WatchlistUpsertRequest,
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        now = container.clock.now()
        existing = {item.symbol: item for item in store.list_watchlist(OWNER_ID)}.get(body.symbol)
        entry = WatchlistEntry(
            symbol=body.symbol,
            name=body.name,
            market=body.market,
            owner_id=OWNER_ID,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            tags=body.tags,
        )
        store.upsert_watchlist(entry)
        _audit(container, session, request, "watchlist.upsert", body.symbol)
        return success_envelope(request, _watchlist_view(entry))

    @router.delete("/watchlist/{symbol}", response_model=ApiEnvelope[WatchlistData])
    async def delete_watchlist(
        request: Request,
        symbol: Annotated[str, Path(pattern=r"^\d{6}$")],
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        if not store.delete_watchlist(OWNER_ID, symbol):
            raise AnalysisError(
                "自选证券不存在",
                error_code="WATCHLIST_NOT_FOUND",
                http_status_code=404,
            )
        _audit(container, session, request, "watchlist.delete", symbol)
        items = tuple(_watchlist_view(item) for item in store.list_watchlist(OWNER_ID))
        return success_envelope(request, WatchlistData(items=items, total=len(items)))

    @router.get("/preferences", response_model=ApiEnvelope[PreferencesData])
    async def get_preferences(
        request: Request,
        _session: OwnerSession = Depends(security.require_owner),
    ):
        items = tuple(_preference_view(item) for item in store.list_preferences(OWNER_ID))
        return success_envelope(request, PreferencesData(items=items))

    @router.put("/preferences", response_model=ApiEnvelope[PreferenceView])
    async def update_preference(
        request: Request,
        body: PreferenceUpdateRequest,
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        value = _validate_preference(body.key, body.value)
        preference = PreferenceRecord(
            owner_id=OWNER_ID,
            key=body.key,
            value_json=json.dumps(value, ensure_ascii=False, separators=(",", ":")),
            updated_at=container.clock.now(),
        )
        store.save_preference(preference)
        _audit(container, session, request, "preference.update", body.key)
        return success_envelope(request, _preference_view(preference))

    @router.post("/scans", response_model=ApiEnvelope[JobView], status_code=202)
    async def create_scan(
        request: Request,
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        if limiter is not None:
            limiter.check_scan(session)
        active = store.get_active_strategy(container.settings.strategy.selected)
        if active is None:
            raise AnalysisError(
                "当前没有已激活的机会策略",
                error_code="NO_ACTIVE_STRATEGY",
                http_status_code=409,
            )
        if container.jobs is None or container.scanner is None:
            raise AnalysisError(
                "扫描任务服务不可用",
                error_code="SCAN_SERVICE_UNAVAILABLE",
                http_status_code=503,
            )
        factor_version = active.definition.factor_version if active.definition else "invalid"
        dedupe_key = (
            f"scan:{active.name}:{active.version}:{factor_version}:"
            f"{container.clock.today().isoformat()}"
        )
        job = container.jobs.submit_scan(
            container.scanner,
            limit=20,
            dedupe_key=dedupe_key,
        )
        _audit(
            container,
            session,
            request,
            "scan.create",
            job.job_id,
            {"strategy": f"{active.name}:{active.version}"},
        )
        envelope = success_envelope(request, _job_view(job), result_status=job.status.value)
        return JSONResponse(status_code=202, content=envelope.model_dump(mode="json"))

    @router.post("/admin/cache/clear", response_model=ApiEnvelope[CacheClearData])
    async def clear_cache(
        request: Request,
        body: CacheClearRequest,
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        if container.cache_store is None:
            raise AnalysisError(
                "缓存服务不可用",
                error_code="CACHE_SERVICE_UNAVAILABLE",
                http_status_code=503,
            )
        cleared = container.cache_store.clear(body.prefix)
        _audit(container, session, request, "cache.clear", body.prefix or "*")
        return success_envelope(request, CacheClearData(cleared=cleared, prefix=body.prefix))

    @router.get("/admin/strategy", response_model=ApiEnvelope[StrategyStatusData])
    async def strategy_status(
        request: Request,
        _session: OwnerSession = Depends(security.require_owner),
    ):
        selected = container.settings.strategy.selected
        active = store.get_active_strategy(selected)
        return success_envelope(request, _strategy_status(selected, active))

    @router.post(
        "/admin/strategies/{name}/{version}/approve",
        response_model=ApiEnvelope[StrategyStatusData],
    )
    async def approve_strategy(
        request: Request,
        name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{1,63}$")],
        version: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")],
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        strategy = strategy_registry.approve(name, version)
        _audit(container, session, request, "strategy.approved", f"{name}:{version}")
        return success_envelope(request, _strategy_version_status(strategy))

    @router.post(
        "/admin/strategies/{name}/{version}/activate",
        response_model=ApiEnvelope[StrategyStatusData],
    )
    async def activate_strategy(
        request: Request,
        name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{1,63}$")],
        version: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")],
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        if name != container.settings.strategy.selected:
            raise AnalysisError(
                "strategy is not selected by production configuration",
                error_code="STRATEGY_NOT_SELECTED",
                http_status_code=409,
            )
        strategy = strategy_registry.activate(name, version)
        _audit(container, session, request, "strategy.activated", f"{name}:{version}")
        return success_envelope(request, _strategy_version_status(strategy))

    @router.post(
        "/admin/strategies/{name}/{version}/retire",
        response_model=ApiEnvelope[StrategyStatusData],
    )
    async def retire_strategy(
        request: Request,
        name: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{1,63}$")],
        version: Annotated[str, Path(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$")],
        session: OwnerSession = Depends(security.require_owner_write),
    ):
        strategy = strategy_registry.retire(name, version)
        _audit(container, session, request, "strategy.retired", f"{name}:{version}")
        return success_envelope(request, _strategy_version_status(strategy))

    @router.get("/admin/diagnostics", response_model=ApiEnvelope[DiagnosticsData])
    async def diagnostics(
        request: Request,
        _session: OwnerSession = Depends(security.require_owner),
    ):
        selected = container.settings.strategy.selected
        active = store.get_active_strategy(selected)
        return success_envelope(
            request,
            DiagnosticsData(
                version=__version__,
                environment=container.settings.runtime.environment,
                public_readonly=container.settings.runtime.public_readonly,
                owner_auth_configured=container.auth.configured,
                analysis_available=container.analysis is not None,
                jobs_available=container.jobs is not None,
                cache_available=container.cache_store is not None,
                strategy_selected=selected,
                strategy_active=active is not None,
            ),
        )

    return router


def _job_view(job: JobRecord) -> JobView:
    return JobView(
        job_id=job.job_id,
        job_type=job.job_type.value,
        status=job.status.value,
        progress=job.progress,
        result_ref=job.result_ref,
        error_code=job.error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
        deadline_at=job.deadline_at,
        cancel_requested=job.cancel_requested,
    )


def _watchlist_view(entry: WatchlistEntry) -> WatchlistView:
    return WatchlistView(
        symbol=entry.symbol,
        name=entry.name,
        market=entry.market,
        tags=entry.tags,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _preference_view(preference: PreferenceRecord) -> PreferenceView:
    return PreferenceView(
        key=preference.key,
        value=json.loads(preference.value_json),
        updated_at=preference.updated_at,
    )


def _validate_preference(key: str, value: Any) -> str | int | bool:
    if key == "theme" and value in {"light", "dark"}:
        return str(value)
    if key == "default_profile" and value in {"standard", "deep"}:
        return str(value)
    if key == "page_size" and type(value) is int and 10 <= value <= 100:
        return value
    raise AnalysisError(
        "偏好值不在允许范围内",
        error_code="INVALID_PREFERENCE",
        http_status_code=400,
    )


def _strategy_status(selected: str, active: Any) -> StrategyStatusData:
    if active is None:
        return StrategyStatusData(selected=selected, active=False)
    return StrategyStatusData(
        selected=selected,
        active=True,
        version=active.version,
        state=active.state.value,
        manifest_hash=active.manifest_hash,
        activated_at=active.activated_at,
    )


def _strategy_version_status(strategy: Any) -> StrategyStatusData:
    return StrategyStatusData(
        selected=strategy.name,
        active=strategy.state.value == "active",
        version=strategy.version,
        state=strategy.state.value,
        manifest_hash=strategy.manifest_hash,
        activated_at=strategy.activated_at,
    )


def _audit(
    container: ApplicationContainer,
    session: OwnerSession,
    request: Request,
    action: str,
    target: str,
    detail: dict[str, Any] | None = None,
) -> None:
    assert container.durable_store is not None
    actor = "owner:" + hashlib.sha256(session.session_id.encode()).hexdigest()[:12]
    container.durable_store.append_audit(
        AuditEvent(
            actor=actor,
            action=action,
            target=target,
            request_id=request_id(request),
            detail_json=json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
            created_at=container.clock.now(),
        )
    )
