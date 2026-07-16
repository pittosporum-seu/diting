"""谛听 · DashboardService — 仪表盘概览、市场情绪、设置管理、缓存管理"""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING

from ...cache.market_state import get_market_state
from ._utils import _BaseService, _get_logger

if TYPE_CHECKING:
    from .scan import ScanService

logger = _get_logger()

_ALL_PROVIDER_KEYS = [
    "provider_eastmoney", "provider_ashare", "provider_mxdata", "provider_akshare"]
_ALL_ENGINE_NAMES = [
    "wyckoff", "buffett", "can_slim", "volume_profile", "vmd_rsi", "verdict"]


class DashboardService(_BaseService):
    """仪表盘 + 市场情绪 + 设置管理 + 缓存管理。"""

    def __init__(
        self,
        scan_service: ScanService | None = None,
        *,
        cache_mgr=None,
        watchlist_db=None,
        settings: dict | None = None,
        repo_factory=None,
    ) -> None:
        super().__init__(cache_mgr=cache_mgr, watchlist_db=watchlist_db,
                         settings=settings, repo_factory=repo_factory)
        self._scan_service = scan_service

    def _get_scan_service(self) -> ScanService:
        """懒加载 ScanService。"""
        if self._scan_service is None:
            from .scan import ScanService
            self._scan_service = ScanService()
        return self._scan_service

    # ── Dashboard ───────────────────────────────────

    def _async_refresh_dashboard(self) -> None:
        """后台异步刷新仪表盘数据。"""
        def _refresh():
            try:
                self.get_dashboard_data(force_refresh=True)
            except Exception:
                pass
        t = threading.Thread(target=_refresh, daemon=True, name="async-dashboard")
        t.start()

    def get_dashboard_data(self, force_refresh: bool = False) -> dict:
        """大盘/仪表盘概览数据（L1 内存 → L2 SQLite → API）。

        v0.6.5: 整合 MarketState，盘后/周末不调 API；支持 force_refresh。
        L1 miss + L2 有 → 立即返回 DB 数据 + 后台异步刷新 API。
        """
        state = get_market_state()

        # L1: 内存缓存命中 → 直接返回
        if not force_refresh:
            cm = self._get_cache_mgr()
            cached = cm.mem_get_adaptive("dashboard", trading_ttl=60)
            if cached is not None:
                cached["_cache_state"] = "stale"
                return cached

        # L2: SQLite dashboard_cache（仅非强刷时读取）
        db_hit = False
        if not force_refresh:
            try:
                cm = self._get_cache_mgr()
                db_row = cm.db_get("dashboard_cache", "1")
                if db_row and db_row.get("data_json"):
                    import json as _json
                    result = _json.loads(db_row["data_json"])
                    result["_cache_state"] = "stale"
                    cm.mem_set("dashboard", result)
                    db_hit = True
                    # v0.6.5: L2 命中后后台异步刷新 API（仅 TRADING 状态）
                    if state.is_trading and not force_refresh:
                        self._async_refresh_dashboard()
                    return result
            except Exception:
                pass

        # v0.6.5: CLOSED/WEEKEND 且无 force_refresh → 返回 DB 数据或空
        empty_dashboard = {
            "status": "ok",
            "watchlist_count": 0,
            "buy_signals": 0,
            "watch_signals": 0,
            "hold_signals": 0,
            "avoid_signals": 0,
            "market_indices": [],
            "vmd_cycle": None,
            "top_opportunities": [],
        }
        if not state.should_call_api and not force_refresh:
            logger.debug(
                "services.dashboard.api_skipped",
                phase=state.phase,
                db_hit=db_hit,
            )
            if db_hit:
                return empty_dashboard
            return empty_dashboard

        try:
            from ...config import Config

            cfg = Config()
            stocks = cfg.load_watchlist(validate=False)
            repo = self._build_repo()

            scan_svc = self._get_scan_service()
            sentiment = self.get_market_sentiment(force_refresh=force_refresh)
            opportunities = scan_svc.get_opportunities()
            buy_count = opportunities["strong_buy"]
            watch_count = opportunities["watch"]
            hold_count = sum(1 for o in opportunities["items"] if 35 <= o["score"] < 50)
            avoid_count = opportunities["avoid"]

            # ── 大盘指数 ──
            market_indices = []
            try:
                index_quotes = repo.get_realtime(["000001.SH", "399001", "399006"])
                index_names = {"000001.SH": "上证指数", "399001": "深证成指", "399006": "创业板指"}
                for code in ["000001.SH", "399001", "399006"]:
                    q = index_quotes.get(code)
                    if q:
                        market_indices.append({
                            "name": index_names.get(code, code),
                            "code": code,
                            "price": q.price,
                            "change_pct": q.change_pct,
                        })
            except Exception:
                logger.warning("services.dashboard.indices_failed")

            # ── VMD 周期 ──
            vmd_cycle = None
            try:
                end = date.today()
                start = end - timedelta(days=250)
                sh_hist = repo.get_historical("000001.SH", start, end)
                if sh_hist is not None and sh_hist.df is not None and len(sh_hist.df) >= 60:
                    close_col = None
                    for c in ["close", "收盘", "收盘价"]:
                        if c in sh_hist.df.columns:
                            close_col = c
                            break
                    if close_col is None:
                        for c in sh_hist.df.columns:
                            if c.lower() == "close":
                                close_col = c
                                break
                    if close_col:
                        close_arr = sh_hist.df[close_col].values
                        if close_arr.dtype == object:
                            close_arr = close_arr.astype(float)
                        try:
                            from ...signals.vmd import VMDDecomposer
                            vmd_result = VMDDecomposer.decompose(
                                close_arr, symbol="000001.SH",
                            )
                            vmd_cycle = {
                                "cycle_position": round(vmd_result.cycle_position * 100, 1),
                                "trend": "upward" if vmd_result.trend_slope > 0 else "downward",
                            }
                        except Exception:
                            logger.warning("services.dashboard.vmd_failed")
            except Exception:
                logger.warning("services.dashboard.vmd_hist_failed")

            # ── 选股机会 Top 5 ──
            top_opportunities = opportunities["items"][:5]

            result = {
                "status": "ok",
                "watchlist_count": len(stocks),
                "buy_signals": buy_count,
                "watch_signals": watch_count,
                "hold_signals": hold_count,
                "avoid_signals": avoid_count,
                "providers": repo.available_providers,
                "market_sentiment": sentiment,
                "market_indices": market_indices,
                "vmd_cycle": vmd_cycle,
                "top_opportunities": top_opportunities,
            }
            self._get_cache_mgr().mem_set("dashboard", result)
            # 写入 SQLite
            try:
                cm = self._get_cache_mgr()
                import json as _json
                cm.db_set("dashboard_cache", "1", {
                    "id": 1,
                    "data_json": _json.dumps(result, default=str, ensure_ascii=False),
                })
            except Exception:
                pass
            return result
        except Exception:
            logger.warning("services.dashboard.failed")
            return {
                "status": "error",
                "watchlist_count": 0,
                "buy_signals": 0,
                "watch_signals": 0,
                "hold_signals": 0,
                "avoid_signals": 0,
                "market_indices": [],
                "vmd_cycle": None,
                "top_opportunities": [],
            }

    # ── Market Sentiment ────────────────────────────

    def get_market_sentiment(self, force_refresh: bool = False) -> dict:
        """市场情绪指标（基于上证指数实时行情）。

        v0.6.5: 支持 force_refresh 绕过 L1 缓存。
        v0.6.5-bugfix: 非交易时段返回空，不调 API。
        """
        if not force_refresh:
            cm = self._get_cache_mgr()
            cached = cm.mem_get_adaptive("market_sentiment", trading_ttl=300)
            if cached is not None:
                cached["_cache_state"] = "stale"
                return cached

        # v0.6.5-bugfix: 非交易时段不调 API
        state = get_market_state()
        if not state.should_call_api and not force_refresh:
            logger.debug(
                "services.market_sentiment.api_skipped",
                phase=state.phase,
            )
            empty = {
                "sentiment": "neutral",
                "sh_index": None,
                "sh_change": None,
                "score": 50,
                "source": "unavailable",
            }
            self._get_cache_mgr().mem_set("market_sentiment", empty)
            return empty

        try:
            repo = self._build_repo()
            quotes = repo.get_realtime(["000001.SH"])
            sh = quotes.get("000001.SH")
            if sh:
                score = 50 + (sh.change_pct * 5 if sh.change_pct else 0)
                score = max(0, min(100, score))
                result = {
                    "sentiment": "bullish" if (sh.change_pct or 0) > 0 else "bearish",
                    "sh_index": sh.price,
                    "sh_change": sh.change_pct,
                    "score": round(score, 1),
                    "source": "realtime",
                    "timestamp": str(datetime.now()),
                }
                self._get_cache_mgr().mem_set("market_sentiment", result)
                return result
        except Exception:
            logger.warning("market_sentiment.failed")
        return {
            "sentiment": "neutral",
            "sh_index": None,
            "sh_change": None,
            "score": 50,
            "source": "unavailable",
        }

    # ── Settings ────────────────────────────────────

    def save_settings(self, data: dict) -> dict:
        """保存设置到 SQLite，持久化跨重启保留。"""
        db = self._db()
        accepted = 0
        for key, val in (data or {}).items():
            if key.startswith("_") or key == "status":
                continue
            try:
                db.set_setting(key, str(val))
                accepted += 1
            except Exception:
                logger.warning("settings.save_key_failed", key=key)
        logger.info("settings.saved", count=accepted)
        return {"status": "ok", "saved": accepted}

    def get_settings(self) -> dict:
        """获取配置信息，合并 DB 持久化值与默认值。"""
        try:
            from ...config import Config

            cfg = Config()
            saved = self._load_saved_settings()
            mx_key = cfg.get("MX_APIKEY")

            # ── 数据源 Toggle ──
            provider_toggles = []
            for pk in _ALL_PROVIDER_KEYS:
                label = pk.replace("provider_", "").replace("mxdata", "mx-data").upper()
                provider_toggles.append({
                    "key": pk,
                    "label": {
                        "ashare": "ashare (新浪/腾讯)",
                        "mxdata": "mx-data (东方财富)",
                        "eastmoney": "east_money (免费直连)",
                        "akshare": "akshare (免费兜底)",
                    }.get(pk.replace("provider_", ""), label),
                    "enabled": saved.get(pk, "1") == "1",
                    "requires_api_key": pk == "provider_mxdata",
                    "api_key_available": bool(mx_key),
                })

            # ── AI Model ──
            saved_model = saved.get("ai_model", "")
            default_model = cfg.get("AI_MODEL") or "deepseek-v4-pro"
            ai_model = saved_model or default_model
            available_models = [
                {"id": "deepseek/deepseek-v4-pro", "label": "DeepSeek V4 Pro"},
                {"id": "deepseek/deepseek-v4-flash", "label": "DeepSeek V4 Flash"},
                {"id": "openai/gpt-4o", "label": "GPT-4o"},
                {"id": "openai/gpt-4o-mini", "label": "GPT-4o Mini"},
            ]

            # ── Engine Toggles ──
            engine_toggles = []
            for en in _ALL_ENGINE_NAMES:
                engine_toggles.append({
                    "key": f"engine_{en}",
                    "name": en,
                    "label": {
                        "wyckoff": "Wyckoff 威克夫分析",
                        "buffett": "Buffett/Munger 综合评分",
                        "can_slim": "CANSLIM 成长股",
                        "volume_profile": "Volume Profile 量价分布",
                        "vmd_rsi": "VMD+RSI 择时信号",
                        "verdict": "Verdict 结论翻译",
                    }.get(en, en),
                    "enabled": saved.get(f"engine_{en}", "1") == "1",
                })

            return {
                "status": "ok",
                "provider_toggles": provider_toggles,
                "ai_model": ai_model,
                "ai_model_label": {
                    "deepseek/deepseek-v4-pro": "DeepSeek V4 Pro",
                    "deepseek/deepseek-v4-flash": "DeepSeek V4 Flash",
                    "openai/gpt-4o": "GPT-4o",
                    "openai/gpt-4o-mini": "GPT-4o Mini",
                }.get(ai_model, ai_model),
                "available_models": available_models,
                "engine_toggles": engine_toggles,
            }
        except Exception:
            logger.warning("services.settings.failed")
            return {
                "status": "ok",
                "provider_toggles": [],
                "ai_model": "deepseek-v4-pro",
                "ai_model_label": "DeepSeek V4 Pro",
                "available_models": [],
                "engine_toggles": [],
            }

    # ── Health & Cache ──────────────────────────────

    def health_check(self) -> dict:
        """服务健康检查。"""
        return {"status": "ok", "service": "diting-web"}

    def get_cache_stats(self) -> dict:
        """获取缓存统计。"""
        cm = self._get_cache_mgr()
        mem = cm.mem_stats()
        db = cm.db_stats()
        return {
            "memory_cache": mem,
            "sqlite_cache": db,
            "updated_at": str(datetime.now()),
        }

    def clear_cache(self) -> dict:
        """清除所有缓存。"""
        cm = self._get_cache_mgr()
        cm.clear_all()
        return {"status": "ok", "message": "所有缓存已清除"}
