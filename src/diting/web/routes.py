"""谛听 · Web 路由 — FastAPI Router

注册 7 个 JSON API 端点 + 2 个 Jinja2 页面路由。
业务逻辑全部在 AnalysisService 中，路由只做请求/响应转换。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Request

from .services import AnalysisService

router = APIRouter()
service = AnalysisService()


# ── Page routes (Jinja2) ────────────────────────────

@router.get("/")
async def search_page(request: Request):
    from .app import templates
    return templates.TemplateResponse(request, "search.html")


@router.get("/stock/{code}")
async def stock_page(request: Request, code: str):
    from .app import templates
    data = service.analyze_stock(code)

    if data["error"]:
        return templates.TemplateResponse(
            request, "result.html",
            {"code": code, "error": data["error"]},
        )

    return templates.TemplateResponse(
        request, "result.html",
        {
            **{k: v for k, v in data.items()
               if not k.startswith("_") and k not in ("signals",)},
            "chart_data": json.dumps(data["chart_data"], ensure_ascii=False),
        },
    )


# ── JSON API routes ────────────────────────────

@router.get("/api/health")
async def api_health():
    return service.health_check()


@router.get("/api/stock/{code}")
async def api_stock(code: str):
    data = service.analyze_stock(code)
    if data["error"]:
        raise HTTPException(status_code=404, detail=data["error"])
    return _to_json_response(data)


@router.get("/api/dashboard")
async def api_dashboard():
    return service.get_dashboard_data()


@router.get("/api/watchlist")
async def api_watchlist():
    return service.get_watchlist()


@router.get("/api/opportunities")
async def api_opportunities():
    return service.get_opportunities()


@router.get("/api/market-sentiment")
async def api_market_sentiment():
    return service.get_market_sentiment()


@router.post("/api/settings")
async def api_settings(request: Request):
    body = await request.json()
    result = service.save_settings(body)
    return result


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


# ── Helpers ────────────────────────────────────

def _to_json_response(data: dict) -> dict:
    """将 analyze_stock 结果转为 JSON 安全的 dict。"""
    signals = data.get("signals")
    return {
        **{k: v for k, v in data.items()
           if not k.startswith("_") and k != "signals"},
        "signals_summary": _signals_to_dict(signals) if signals else None,
    }


def _signals_to_dict(sig) -> dict:
    return {
        "rsi_14": sig.rsi_14,
        "macd": sig.macd,
        "macd_signal_line": sig.macd_signal_line,
        "macd_histogram": sig.macd_histogram,
        "kdj_k": sig.kdj_k,
        "kdj_d": sig.kdj_d,
        "kdj_j": sig.kdj_j,
        "bollinger_upper": sig.bollinger_upper,
        "bollinger_middle": sig.bollinger_middle,
        "bollinger_lower": sig.bollinger_lower,
        "bollinger_position": sig.bollinger_position,
        "ma_5": sig.ma_5,
        "ma_20": sig.ma_20,
        "ma_60": sig.ma_60,
        "vwap": sig.vwap,
        "vwap_deviation": sig.vwap_deviation,
        "volume_ratio": sig.volume_ratio,
    }
