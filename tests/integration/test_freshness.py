"""数据新鲜度测试 — 验证 freshness 字段在所有端点正确注入。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from unittest.mock import patch

    with patch("src.diting.web.app.start_prefetch_worker"):
        from src.diting.web.app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


# 需要包含 freshness 的数据端点
FRESHNESS_ENDPOINTS = [
    "/api/stock/002475",
    "/api/dashboard",
    "/api/watchlist",
    "/api/opportunities",
    "/api/market-sentiment",
    "/api/stock-search?q=002",
    "/api/stock-list",
]


class TestFreshnessPresence:
    """所有数据端点都应包含 freshness 字段。"""

    @pytest.mark.parametrize("endpoint", FRESHNESS_ENDPOINTS)
    def test_freshness_present(self, client: TestClient, endpoint: str):
        resp = client.get(endpoint)
        assert resp.status_code == 200, f"{endpoint} returned {resp.status_code}"
        body = resp.json()
        assert "freshness" in body, f"{endpoint} 缺少 freshness 字段"

    @pytest.mark.parametrize("endpoint", FRESHNESS_ENDPOINTS)
    def test_freshness_has_required_fields(self, client: TestClient, endpoint: str):
        resp = client.get(endpoint)
        body = resp.json()
        f = body.get("freshness")
        if f is None:
            pytest.skip(f"{endpoint} 无 freshness")
        assert "data_time" in f
        assert "source" in f
        assert "is_fresh" in f
        assert "age_seconds" in f
        assert "ttl_seconds" in f


class TestFreshnessConsistency:
    """freshness 字段内部一致性。"""

    @pytest.mark.parametrize("endpoint", FRESHNESS_ENDPOINTS)
    def test_data_time_not_future(self, client: TestClient, endpoint: str):
        resp = client.get(endpoint)
        body = resp.json()
        f = body.get("freshness")
        if not f or not f.get("data_time"):
            pytest.skip("无 data_time")
        data_time = datetime.fromisoformat(f["data_time"])
        now = datetime.now(UTC)
        # 统一为 aware UTC
        if data_time.tzinfo is None:
            data_time = data_time.replace(tzinfo=UTC)
        # data_time 不应超过当前时间（允许 5s 时钟偏差）
        from datetime import timedelta
        assert data_time <= now + timedelta(seconds=5), (
            f"data_time {data_time} 在未来 (now={now})"
        )

    @pytest.mark.parametrize("endpoint", FRESHNESS_ENDPOINTS)
    def test_server_time_gte_data_time(self, client: TestClient, endpoint: str):
        """server_time（响应时间）应 >= data_time（数据时间）。"""
        resp = client.get(endpoint)
        body = resp.json()
        f = body.get("freshness")
        if not f or not f.get("data_time"):
            pytest.skip("无 data_time")
        server_time = datetime.fromisoformat(body["server_time"])
        data_time = datetime.fromisoformat(f["data_time"])
        # 统一 tz
        if server_time.tzinfo is None:
            server_time = server_time.replace(tzinfo=UTC)
        if data_time.tzinfo is None:
            data_time = data_time.replace(tzinfo=UTC)
        assert server_time >= data_time, (
            f"server_time {server_time} < data_time {data_time}"
        )

    @pytest.mark.parametrize("endpoint", FRESHNESS_ENDPOINTS)
    def test_age_seconds_non_negative(self, client: TestClient, endpoint: str):
        resp = client.get(endpoint)
        body = resp.json()
        f = body.get("freshness")
        if not f:
            pytest.skip("无 freshness")
        assert f["age_seconds"] >= 0


class TestFreshnessSource:
    """验证 source 标识合理。"""

    def test_static_endpoints_marked_static(self, client: TestClient):
        """stock-search 和 stock-list 是静态数据。"""
        for ep in ["/api/stock-search?q=002", "/api/stock-list"]:
            resp = client.get(ep)
            body = resp.json()
            f = body.get("freshness", {})
            assert f.get("source") == "static", f"{ep} source 应为 static"

    def test_dashboard_source_is_cache_or_realtime(self, client: TestClient):
        resp = client.get("/api/dashboard")
        body = resp.json()
        f = body.get("freshness", {})
        valid_sources = ("cache", "realtime", "memory_cache", "sqlite_cache", "unknown", "unavailable")
        assert f.get("source") in valid_sources
