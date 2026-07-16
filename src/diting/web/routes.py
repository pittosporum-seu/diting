"""谛听 · Web 路由 — FastAPI Router

注册 7 个 JSON API 端点 + 2 个 Jinja2 页面路由。
业务逻辑全部在 AnalysisService 中，路由只做请求/响应转换。
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Request

from ..cache import CacheManager
from ..infra.errors import AnalysisError, DataUnavailableError
from .services import DashboardService, ScanService, StockService, WatchlistService

router = APIRouter()
_cache_mgr = CacheManager()
stock_service = StockService(cache_mgr=_cache_mgr)
scan_service = ScanService(cache_mgr=_cache_mgr)
dashboard_service = DashboardService(cache_mgr=_cache_mgr, scan_service=scan_service)
watchlist_service = WatchlistService(cache_mgr=_cache_mgr)
# ── API response wrapper ────────────────────────

def _api_response(data: dict, cache_state: str | None = None) -> dict:
    """Wrap API data with server_time and cache_state.

    All JSON API endpoints MUST use this wrapper so the frontend
    has an authoritative timestamp and freshness indicator.
    """
    resp = {
        "server_time": datetime.now(UTC).isoformat(),
        "data": data,
    }
    # Derive cache_state from data if not explicitly provided
    if cache_state:
        resp["cache_state"] = cache_state
    elif "_cache_state" in data:
        resp["cache_state"] = data.pop("_cache_state")
    else:
        resp["cache_state"] = "fresh"
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
            request, "result.html",
            {"code": code, "error": data["error"]},
        )

    return templates.TemplateResponse(
        request, "result.html",
        {
            **{k: v for k, v in data.items()
               if not k.startswith("_") and k != "signals_summary"},
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
async def api_stock(code: str):
    resp = stock_service.analyze_stock(code)
    if resp.error:
        raise DataUnavailableError(message=resp.error)
    data = asdict(resp)
    cs = data.pop("_cache_state", "fresh")
    return _api_response(data, cache_state=cs)


@router.get("/api/stock-search")
async def api_stock_search(q: str = ""):
    """股票搜索：支持6位代码或中文名称模糊匹配。"""
    results = stock_service.search_stock(q)
    return _api_response({"results": results})


@router.get("/api/stock-list")
async def api_stock_list():
    """返回全市场 A 股股票列表 [{code, name}]。"""
    data = stock_service.get_stock_list()
    return _api_response(data if isinstance(data, dict) else {"items": data})


@router.get("/api/dashboard")
async def api_dashboard():
    data = dashboard_service.get_dashboard_data()
    cs = data.get("_cache_state", "fresh") if isinstance(data, dict) else "fresh"
    return _api_response(data, cache_state=cs)


@router.get("/api/watchlist")
async def api_watchlist():
    data = watchlist_service.get_watchlist()
    return _api_response({"items": data})


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
        raise AnalysisError(
            message="自选股不存在", error_code="NOT_FOUND", http_status_code=404
        )
    return _api_response({"status": "ok", "code": code})


@router.get("/api/opportunities")
async def api_opportunities():
    data = scan_service.get_opportunities()
    cs = data.get("_cache_state", "fresh") if isinstance(data, dict) else "fresh"
    return _api_response(data, cache_state=cs)


@router.get("/api/market-sentiment")
async def api_market_sentiment():
    data = dashboard_service.get_market_sentiment()
    cs = data.get("_cache_state", "fresh") if isinstance(data, dict) else "fresh"
    return _api_response(data, cache_state=cs)


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
