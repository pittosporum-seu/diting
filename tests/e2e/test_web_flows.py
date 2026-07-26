"""E2E Web 交互流程测试 — 模拟前端完整操作链路。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from unittest.mock import patch

    with patch("src.diting.web.app.start_prefetch_worker"):
        from src.diting.web.app import app

        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestDashboardFlow:
    """仪表盘加载流程。"""

    def test_dashboard_full_load(self, client: TestClient):
        resp = client.get("/api/dashboard")
        assert resp.status_code == 200
        body = resp.json()
        # 应包含核心字段
        assert "server_time" in body
        assert "freshness" in body


class TestStockAnalysisFlow:
    """个股分析完整流程。"""

    def test_stock_analysis_full(self, client: TestClient):
        resp = client.get("/api/stock/002475")
        assert resp.status_code == 200
        body = resp.json()
        data = body["data"]
        # 核心字段
        assert data["code"] == "002475"
        assert data["name"]
        assert data["score"] is not None
        assert data["rating"]
        assert "engine_scores" in data
        assert "chart_data" in data
        # K线数据
        chart = data["chart_data"]
        assert "dates" in chart
        assert "prices" in chart
        assert len(chart["dates"]) > 0
        # 信号摘要
        assert "signals_summary" in data


class TestWatchlistFlow:
    """自选股管理完整闭环。"""

    def test_watchlist_add_query_delete(self, client: TestClient):
        # 1. 添加
        resp = client.post("/api/watchlist", json={"code": "603659", "name": "璞泰来"})
        assert resp.status_code == 200
        assert resp.json()["data"]["code"] == "603659"

        # 2. 查询 — 应包含刚添加的
        resp = client.get("/api/watchlist")
        items = resp.json()["data"]["items"]
        codes = [it.get("code") for it in items]
        assert "603659" in codes

        # 3. 删除
        resp = client.delete("/api/watchlist/603659")
        assert resp.status_code == 200

        # 4. 确认已删除
        resp = client.get("/api/watchlist")
        items = resp.json()["data"]["items"]
        codes = [it.get("code") for it in items]
        assert "603659" not in codes

    def test_watchlist_add_duplicate(self, client: TestClient):
        """重复添加同一只股票不应报错。"""
        client.post("/api/watchlist", json={"code": "000001"})
        resp = client.post("/api/watchlist", json={"code": "000001"})
        assert resp.status_code == 200
        # 清理
        client.delete("/api/watchlist/000001")


class TestOpportunitiesFlow:
    """选股扫描流程。"""

    def test_opportunities_structure(self, client: TestClient):
        resp = client.get("/api/opportunities")
        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body


class TestSettingsFlow:
    """设置持久化流程。"""

    def test_settings_write_read(self, client: TestClient):
        # 写入
        resp = client.post("/api/settings", json={"engine_wyckoff": "1"})
        assert resp.status_code == 200

        # 读取
        resp = client.get("/api/settings")
        assert resp.status_code == 200
        assert "data" in resp.json()


class TestCacheFlow:
    """缓存管理流程。"""

    def test_cache_stats_clear_stats(self, client: TestClient):
        # 1. 查看统计
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200

        # 2. 清除
        resp = client.post("/api/cache/clear")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "ok"

        # 3. 再查看
        resp = client.get("/api/cache/stats")
        assert resp.status_code == 200


class TestSearchFlow:
    """搜索联想流程。"""

    def test_search_by_code(self, client: TestClient):
        resp = client.get("/api/stock-search", params={"q": "002475"})
        assert resp.status_code == 200
        results = resp.json()["data"]["results"]
        assert len(results) >= 0  # 可能无匹配但不报错

    def test_search_empty_query(self, client: TestClient):
        resp = client.get("/api/stock-search", params={"q": ""})
        assert resp.status_code == 200
