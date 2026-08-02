"""谛听 · Web 路由 — FastAPI Router

注册 7 个 JSON API 端点 + 2 个 Jinja2 页面路由。
业务逻辑全部在 AnalysisService 中，路由只做请求/响应转换。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from ..bootstrap import bootstrap_runtime
from ..cache import CacheManager
from ..infra.errors import AnalysisError, DataUnavailableError
from ..schema import FreshnessInfo
from .security import build_auth_router
from .services import DashboardService, ScanService, StockService, WatchlistService
from .v1 import build_v1_router

router = APIRouter()
container = bootstrap_runtime()
assert container.auth is not None
router.include_router(build_auth_router(container.auth, container.settings))
router.include_router(build_v1_router(container))
_cache_mgr = CacheManager()
stock_service = StockService(cache_mgr=_cache_mgr, data_gateway=container.data_gateway)
scan_service = ScanService(cache_mgr=_cache_mgr, data_gateway=container.data_gateway)
scan_service.set_stock_service(stock_service)  # 支持候选股深度分析
dashboard_service = DashboardService(
    cache_mgr=_cache_mgr,
    scan_service=scan_service,
    data_gateway=container.data_gateway,
)
watchlist_service = WatchlistService(
    cache_mgr=_cache_mgr,
    data_gateway=container.data_gateway,
)
# ── API response wrapper ────────────────────────


def _build_freshness(
    data_time: datetime | None = None,
    source: str = "unknown",
    ttl_seconds: int = 60,
) -> FreshnessInfo:
    """Build a FreshnessInfo from available metadata."""
    now = datetime.now(UTC)
    if data_time is None:
        data_time = now
    if data_time.tzinfo is None:
        data_time = data_time.replace(tzinfo=UTC)
    age = (now - data_time).total_seconds()
    return FreshnessInfo(
        data_time=data_time,
        source=source,
        is_fresh=age <= ttl_seconds,
        age_seconds=round(age, 1),
        ttl_seconds=ttl_seconds,
    )


def _extract_freshness(data: dict, default_ttl: int = 60) -> FreshnessInfo | None:
    """Extract freshness from _cached_at / _cache_state fields in service data."""
    if not isinstance(data, dict):
        return None
    cached_at = data.pop("_cached_at", None)
    cache_state = data.pop("_cache_state", None)
    if isinstance(cached_at, str):
        try:
            cached_at = datetime.fromisoformat(cached_at)
        except (ValueError, TypeError):
            cached_at = None
    if isinstance(cached_at, datetime):
        return _build_freshness(cached_at, source="cache", ttl_seconds=default_ttl)
    if cache_state:
        source = "realtime" if cache_state == "fresh" else "cache"
        return _build_freshness(source=source, ttl_seconds=default_ttl)
    return None


def _api_response(
    data: dict,
    *,
    freshness: FreshnessInfo | None = None,
    error: str | None = None,
) -> dict:
    """Wrap API data with server_time and optional freshness.

    All JSON API endpoints MUST use this wrapper so the frontend
    has an authoritative timestamp and freshness indicator.
    """
    resp = {
        "server_time": datetime.now(UTC).isoformat(),
        "data": data,
    }
    if freshness:
        resp["freshness"] = {
            "data_time": freshness.data_time.isoformat() if freshness.data_time else None,
            "source": freshness.source,
            "is_fresh": freshness.is_fresh,
            "age_seconds": freshness.age_seconds,
            "ttl_seconds": freshness.ttl_seconds,
        }
    if error:
        resp["error"] = error
    return resp


# ── Page routes (Jinja2) ────────────────────────────


@router.get("/")
async def search_page(request: Request):
    from .app import templates

    return templates.TemplateResponse(request, "search.html")


@router.get("/stock/{code}")
async def stock_page(request: Request, code: str):
    from .app import templates

    resp = stock_service.analyze_stock(code)
    data = asdict(resp)

    if data.get("error"):
        return templates.TemplateResponse(
            request,
            "result.html",
            {"code": code, "error": data["error"]},
        )

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            **{k: v for k, v in data.items() if not k.startswith("_") and k != "signals_summary"},
            "chart_data": json.dumps(data.get("chart_data", {}), ensure_ascii=False),
        },
    )


# ── JSON API routes ────────────────────────────


@router.get("/api/health")
async def api_health():
    return _api_response(dashboard_service.health_check())


@router.get("/api/stock-name/{code}")
async def api_stock_name(code: str):
    """根据股票代码获取名称。"""
    name = stock_service.get_stock_name(code)
    return _api_response({"code": code, "name": name})


@router.get("/api/stock/{code}")
async def api_stock(code: str, force: bool = False):
    resp = stock_service.analyze_stock(code, force=force)
    if resp.error:
        raise DataUnavailableError(message=resp.error)
    data = asdict(resp)
    freshness = _extract_freshness(data, default_ttl=60)
    return _api_response(data, freshness=freshness)


@router.get("/api/stock-search")
async def api_stock_search(q: str = ""):
    """股票搜索：支持6位代码或中文名称模糊匹配。"""
    results = stock_service.search_stock(q)
    freshness = _build_freshness(source="static", ttl_seconds=86400)
    return _api_response({"results": results}, freshness=freshness)


@router.get("/api/stock-list")
async def api_stock_list():
    """返回全市场 A 股股票列表 [{code, name}]。"""
    data = stock_service.get_stock_list()
    freshness = _build_freshness(source="static", ttl_seconds=86400)
    return _api_response(data if isinstance(data, dict) else {"items": data}, freshness=freshness)


@router.get("/api/dashboard")
async def api_dashboard():
    data, freshness = dashboard_service.get_dashboard_data()
    return _api_response(data, freshness=freshness)


@router.get("/api/watchlist")
async def api_watchlist():
    data = watchlist_service.get_watchlist()
    freshness = _build_freshness(source="cache", ttl_seconds=300)
    return _api_response({"items": data}, freshness=freshness)


@router.post("/api/watchlist")
async def api_watchlist_add(request: Request):
    """添加自选股 → POST /api/watchlist  {code, name?, market?}"""
    body = await request.json()
    code = (body.get("code") or "").strip()
    if not code or not (code.isdigit() and len(code) == 6):
        raise ValueError("code 必须是6位数字")
    result = watchlist_service.add_watchlist(code, body.get("name", ""), body.get("market", "sz"))
    if not result:
        raise AnalysisError(message="添加失败", error_code="WATCHLIST_ADD_FAILED")
    return _api_response({"status": "ok", "code": code})


@router.delete("/api/watchlist/{code}")
async def api_watchlist_remove(code: str):
    """删除自选股 → DELETE /api/watchlist/{code}"""
    if not code or not (code.isdigit() and len(code) == 6):
        raise ValueError("code 必须是6位数字")
    ok = watchlist_service.remove_watchlist(code)
    if not ok:
        raise AnalysisError(message="自选股不存在", error_code="NOT_FOUND", http_status_code=404)
    return _api_response({"status": "ok", "code": code})


@router.get("/api/opportunities")
async def api_opportunities():
    data = scan_service.get_opportunities()
    freshness = _extract_freshness(data, default_ttl=120) if isinstance(data, dict) else None
    if freshness is None:
        freshness = _build_freshness(source="cache", ttl_seconds=120)
    return _api_response(data, freshness=freshness)


@router.get("/api/analysis/progress")
async def api_analysis_progress():
    """查询后台深度分析进度。"""
    progress = scan_service.get_deep_progress()
    if progress is None:
        progress = {"status": "unavailable", "total": 0, "done": 0}
    return _api_response(progress)


@router.post("/api/analysis/refresh")
async def api_analysis_refresh():
    """显式触发全量重跑：强制重扫机会并对候选跑全量分析（忽略缓存与休市限制）。"""
    data = scan_service.get_opportunities(force_refresh=True)
    progress = scan_service.get_deep_progress()
    return _api_response(
        {
            "status": "ok",
            "total": data.get("total", 0) if isinstance(data, dict) else 0,
            "progress": progress,
        }
    )


@router.get("/api/market-sentiment")
async def api_market_sentiment():
    data = dashboard_service.get_market_sentiment()
    # 从 service 返回的 dict 中提取 _cached_at，构造 FreshnessInfo
    cached_at = data.pop("_cached_at", None) if isinstance(data, dict) else None
    if isinstance(cached_at, str):
        cached_at = datetime.fromisoformat(cached_at)
    freshness = None
    if cached_at and isinstance(cached_at, datetime):
        freshness = FreshnessInfo(
            data_time=cached_at,
            source=data.get("source", "unknown"),
            is_fresh=data.get("source") == "realtime",
            age_seconds=(datetime.now(UTC) - cached_at).total_seconds(),
            ttl_seconds=300,
        )
    return _api_response(data, freshness=freshness)


@router.get("/api/settings")
async def api_get_settings():
    return _api_response(dashboard_service.get_settings())


@router.post("/api/settings")
async def api_save_settings(request: Request):
    body = await request.json()
    result = dashboard_service.save_settings(body)
    return _api_response(result)


# ── Cache management ────────────────────────────


@router.get("/api/cache/stats")
async def api_cache_stats():
    return _api_response(dashboard_service.get_cache_stats())


@router.post("/api/cache/clear")
async def api_cache_clear():
    return _api_response(dashboard_service.clear_cache())


@router.post("/api/cache/refresh-scan")
async def api_cache_refresh_scan():
    return _api_response(scan_service.refresh_market_scan())


# ── SPA catch-all ────────────────────────────


@router.get("/{path:path}")
async def spa_files(path: str):
    """Serve SPA static files for non-API paths."""
    from fastapi.responses import FileResponse

    from .app import FRONTEND

    fp = FRONTEND / path
    if fp.exists() and fp.is_file():
        return FileResponse(fp)
    return FileResponse(FRONTEND / "index.html")
