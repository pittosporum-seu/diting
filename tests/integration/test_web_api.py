"""Web API 端点集成测试 — 覆盖全部 16 个端点。

使用 FastAPI TestClient，不依赖外部网络（数据源通过 ashare 免费接口）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    """创建测试用 TestClient，跳过 prefetch worker。"""
    from unittest.mock import patch

    with patch("src.diting.web.app.start_prefetch_worker"):
        from src.diting.web.app import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# ═══════════════════════════════════════════
# 基础端点
# ═══════════════════════════════════════════


class TestHealthAndBasic:
    def test_health(self, client: TestClient):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["status"] == "ok"
        assert body["data"]["service"] == "diting-web"
        assert "server_time" in body

    def test_stock_name(self, client: TestClient):
        resp = client.get("/api/stock-name/002475")
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["code"] == "002475"
        assert body["data"]["name"]  # 非空

    def test_stock_search(self, client: TestClient):
        resp = client.get("/api/stock-search", params={"q": "002475"})
        assert resp.status_code == 200
        body = resp.json()
        assert "results" in body["data"]

    def test_stock_list(self, client: TestClient):
        resp = client.get("/api/stock-list")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body["data"]


# ═══════════════════════════════════════════
# 个股分析
# ═══════════════════════════════════════════


class TestStockAnalysis:
    def test_stock_analysis(self, client: TestClient):
        resp = client.get("/api/stock/002475")
        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]
        assert data["code"] == "002475"
        assert data["score"] is not None
        assert data["rating"] is not None
        assert "engine_scores" in data

    def test_stock_analysis_has_freshness(self, client: TestClient):
        resp = client.get("/api/stock/002475")
        body = resp.json()
        assert "freshness" in body, "stock 端点应包含 freshness"
        f = body["freshness"]
        assert f["data_time"] is not None
        assert f["source"] in ("realtime", "cache", "unknown")

    def test_unknown_stock_returns_gracefully(self, client: TestClient):
        """未知股票代码应返回 200（零值数据）或错误，不应崩溃。"""
        resp = client.get("/api/stock/999999")
        assert resp.status_code in (200, 418, 503)
        body = resp.json()
        # 要么返回零值数据，要么返回错误
        data = body.get("data", {})
        is_zero_data = data.get("price", 0) == 0 or data.get("score") is None
        has_error = body.get("error") or body.get("success") is False or data.get("error")
        assert is_zero_data or has_error


# ═══════════════════════════════════════════
# 仪表盘 & 市场情绪
# ═══════════════════════════════════════════


class TestDashboard:
    def test_dashboard(self, client: TestClient):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body

    def test_dashboard_has_freshness(self, client: TestClient):
        resp = client.get("/api/dashboard")
        body = resp.json()
        assert "freshness" in body
        f = body["freshness"]
        assert f["data_time"] is not None

    def test_market_sentiment(self, client: TestClient):
        resp = client.get("/api/market-sentiment")
        assert resp.status_code == 200
        body = resp.json()
        assert "sentiment" in body["data"]


# ═══════════════════════════════════════════
# 自选股 CRUD
# ═══════════════════════════════════════════


class TestWatchlistCRUD:
    def test_watchlist_crud(self, client: TestClient):
        # 添加
        resp = client.post("/api/watchlist", json={"code": "600519", "name": "贵州茅台"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"

        # 查询
        resp = client.get("/api/watchlist")
        assert resp.status_code == 200
        items = resp.json()["data"]["items"]
        codes = [it.get("code") for it in items]
        assert "600519" in codes

        # 删除
        resp = client.delete("/api/watchlist/600519")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"

        # 确认已删除
        resp = client.get("/api/watchlist")
        items = resp.json()["data"]["items"]
        codes = [it.get("code") for it in items]
        assert "600519" not in codes

    def test_watchlist_has_freshness(self, client: TestClient):
        resp = client.get("/api/watchlist")
        body = resp.json()
        assert "freshness" in body

    def test_watchlist_invalid_code(self, client: TestClient):
        resp = client.post("/api/watchlist", json={"code": "abc"})
        assert resp.status_code == 400


# ═══════════════════════════════════════════
# 选股机会
# ═══════════════════════════════════════════


class TestOpportunities:
    def test_opportunities(self, client: TestClient):
        resp = client.get("/api/opportunities")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body

    def test_opportunities_has_freshness(self, client: TestClient):
        resp = client.get("/api/opportunities")
        body = resp.json()
        assert "freshness" in body


# ═══════════════════════════════════════════
# 设置
# ═══════════════════════════════════════════


class TestSettings:
    def test_settings_get(self, client: TestClient):
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        assert "data" in resp.json()

    def test_settings_get_set(self, client: TestClient):
        # 写入
        resp = client.post("/api/settings", json={"test_key": "test_value"})
        assert resp.status_code == 200

        # 读取
        resp = client.get("/api/settings")
        assert resp.status_code == 200


# ═══════════════════════════════════════════
# 缓存管理
# ═══════════════════════════════════════════


class TestCacheManagement:
    def test_cache_stats(self, client: TestClient):
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert "memory_cache" in data or "sqlite_cache" in data

    def test_cache_clear(self, client: TestClient):
        resp = client.post("/api/cache/clear")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"
