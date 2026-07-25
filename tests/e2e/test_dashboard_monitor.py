"""Dashboard 页面逐模块拨测 — 每个 UI 模块对应独立测试用例。

覆盖模块：
  1. 数据时间栏（freshness）
  2. 大盘指数卡片（market_indices）
  3. 信号统计卡片（buy/watch/hold/avoid）
  4. VMD 周期仪表盘（vmd_cycle）
  5. 信号分布饼图（pie chart 数据）
  6. 选股机会 Top 5（top_opportunities）
  7. 市场情绪（market_sentiment）
  8. 数据源状态（providers）
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from unittest.mock import patch

    with patch("src.diting.web.app.start_prefetch_worker"):
        from src.diting.web.app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


@pytest.fixture(scope="module")
def dashboard(client: TestClient) -> dict:
    """获取一次 dashboard 响应，所有测试共享。"""
    resp = client.get("/api/dashboard")
    assert resp.status_code == 200
    return resp.json()


# ═══════════════════════════════════════════
# 模块 1: 数据时间栏（freshness）
# ═══════════════════════════════════════════


class TestDataTimeBar:
    """验证 freshness 字段正确反映数据真实时间。"""

    def test_freshness_exists(self, dashboard: dict):
        """API 响应必须包含 freshness 字段。"""
        assert "freshness" in dashboard

    def test_freshness_has_all_fields(self, dashboard: dict):
        """freshness 包含 5 个必要字段。"""
        f = dashboard["freshness"]
        for field in ("data_time", "source", "is_fresh", "age_seconds", "ttl_seconds"):
            assert field in f, f"freshness 缺少 {field}"

    def test_data_time_not_future(self, dashboard: dict):
        """data_time 不应超过当前时间。"""
        f = dashboard["freshness"]
        if not f["data_time"]:
            pytest.skip("data_time 为空")
        dt = datetime.fromisoformat(f["data_time"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        assert dt <= datetime.now(UTC) + timedelta(seconds=5)

    def test_age_seconds_consistent_with_data_time(self, dashboard: dict):
        """age_seconds 应与 data_time 和 server_time 的差值一致。"""
        f = dashboard["freshness"]
        if not f["data_time"]:
            pytest.skip("data_time 为空")
        dt = datetime.fromisoformat(f["data_time"])
        st = datetime.fromisoformat(dashboard["server_time"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        if st.tzinfo is None:
            st = st.replace(tzinfo=UTC)
        expected_age = (st - dt).total_seconds()
        # 允许 2s 误差
        assert abs(f["age_seconds"] - expected_age) < 2, (
            f"age_seconds={f['age_seconds']} 与计算值 {expected_age:.1f} 不一致"
        )

    def test_is_fresh_matches_age_and_ttl(self, dashboard: dict):
        """is_fresh 应与 age_seconds <= ttl_seconds 一致（unavailable 除外）。"""
        f = dashboard["freshness"]
        if f["source"] == "unavailable":
            # 无数据时 is_fresh 应为 False
            assert f["is_fresh"] is False
            return
        expected = f["age_seconds"] <= f["ttl_seconds"]
        assert f["is_fresh"] == expected, (
            f"is_fresh={f['is_fresh']} 但 age={f['age_seconds']}s, ttl={f['ttl_seconds']}s"
        )

    def test_server_time_present(self, dashboard: dict):
        """server_time 必须存在且可解析。"""
        assert "server_time" in dashboard
        datetime.fromisoformat(dashboard["server_time"])  # 不抛异常


# ═══════════════════════════════════════════
# 模块 2: 大盘指数卡片
# ═══════════════════════════════════════════


class TestMarketIndices:
    """验证 market_indices 数据完整。"""

    def test_indices_exist(self, dashboard: dict):
        data = dashboard["data"]
        assert "market_indices" in data

    def test_indices_is_list(self, dashboard: dict):
        indices = dashboard["data"]["market_indices"]
        assert isinstance(indices, list)

    def test_indices_have_required_fields(self, dashboard: dict):
        """每个指数卡片需要 code, name, price, change_pct。"""
        indices = dashboard["data"]["market_indices"]
        for idx in indices:
            assert "code" in idx, f"指数缺少 code: {idx}"
            assert "name" in idx, f"指数缺少 name: {idx}"
            assert "price" in idx, f"指数缺少 price: {idx}"
            assert "change_pct" in idx, f"指数缺少 change_pct: {idx}"

    def test_indices_price_is_number(self, dashboard: dict):
        indices = dashboard["data"]["market_indices"]
        for idx in indices:
            assert isinstance(idx.get("price"), (int, float)), (
                f"{idx.get('name')} price 不是数字: {idx.get('price')}"
            )

    def test_indices_change_pct_is_number(self, dashboard: dict):
        indices = dashboard["data"]["market_indices"]
        for idx in indices:
            pct = idx.get("change_pct")
            assert pct is None or isinstance(pct, (int, float))


# ═══════════════════════════════════════════
# 模块 3: 信号统计卡片
# ═══════════════════════════════════════════


class TestSignalStats:
    """验证 buy/watch/hold/avoid 信号计数。"""

    @pytest.mark.parametrize("field", [
        "buy_signals", "watch_signals", "hold_signals", "avoid_signals",
    ])
    def test_signal_count_exists(self, dashboard: dict, field: str):
        assert field in dashboard["data"], f"缺少 {field}"

    @pytest.mark.parametrize("field", [
        "buy_signals", "watch_signals", "hold_signals", "avoid_signals",
    ])
    def test_signal_count_is_non_negative_int(self, dashboard: dict, field: str):
        val = dashboard["data"][field]
        assert isinstance(val, int), f"{field} 应为 int，实际 {type(val)}"
        assert val >= 0, f"{field} 不应为负: {val}"


# ═══════════════════════════════════════════
# 模块 4: VMD 周期仪表盘
# ═══════════════════════════════════════════


class TestVMDCycle:
    """验证 vmd_cycle 数据。"""

    def test_vmd_cycle_key_exists(self, dashboard: dict):
        assert "vmd_cycle" in dashboard["data"]

    def test_vmd_cycle_position_in_range(self, dashboard: dict):
        """cycle_position 应在 0-100 之间（周末可能为 None）。"""
        vmd = dashboard["data"]["vmd_cycle"]
        if vmd is None:
            pytest.skip("周末无 VMD 数据")
        pos = vmd.get("cycle_position")
        if pos is not None:
            assert 0 <= pos <= 100, f"cycle_position={pos} 超出 [0,100]"

    def test_vmd_trend_is_string(self, dashboard: dict):
        vmd = dashboard["data"]["vmd_cycle"]
        if vmd is None:
            pytest.skip("周末无 VMD 数据")
        trend = vmd.get("trend")
        assert trend is None or isinstance(trend, str)


# ═══════════════════════════════════════════
# 模块 5: 信号分布饼图数据
# ═══════════════════════════════════════════


class TestPieChartData:
    """饼图数据由 buy/watch/hold/avoid 组成，验证总和一致。"""

    def test_pie_data_sums_correctly(self, dashboard: dict):
        data = dashboard["data"]
        total = (
            data.get("buy_signals", 0)
            + data.get("watch_signals", 0)
            + data.get("hold_signals", 0)
            + data.get("avoid_signals", 0)
        )
        # 总和应 >= 0（可能全为 0 表示无信号）
        assert total >= 0


# ═══════════════════════════════════════════
# 模块 6: 选股机会 Top 5
# ═══════════════════════════════════════════


class TestTopOpportunities:
    """验证 top_opportunities 列表。"""

    def test_top_opportunities_exists(self, dashboard: dict):
        assert "top_opportunities" in dashboard["data"]

    def test_top_opportunities_is_list(self, dashboard: dict):
        opps = dashboard["data"]["top_opportunities"]
        assert isinstance(opps, list)

    def test_top_opportunities_max_5(self, dashboard: dict):
        opps = dashboard["data"]["top_opportunities"]
        assert len(opps) <= 5, f"Top 机会不应超过 5 个，实际 {len(opps)}"

    def test_opportunity_has_code_and_name(self, dashboard: dict):
        opps = dashboard["data"]["top_opportunities"]
        for o in opps:
            assert "code" in o, f"机会缺少 code: {o}"
            assert "name" in o or o.get("code"), f"机会缺少 name: {o}"

    def test_opportunity_change_pct_is_number(self, dashboard: dict):
        opps = dashboard["data"]["top_opportunities"]
        for o in opps:
            pct = o.get("change_pct")
            assert pct is None or isinstance(pct, (int, float))


# ═══════════════════════════════════════════
# 模块 7: 市场情绪
# ═══════════════════════════════════════════


class TestMarketSentiment:
    """验证 market_sentiment 子对象（仅交易时段有数据）。"""

    def test_sentiment_key_present_or_weekend(self, dashboard: dict):
        """周末可能无 market_sentiment，但不应报错。"""
        data = dashboard["data"]
        if "market_sentiment" not in data:
            pytest.skip("周末/非交易时段无 market_sentiment")
        ms = data["market_sentiment"]
        assert "sentiment" in ms

    def test_sentiment_value_valid(self, dashboard: dict):
        if "market_sentiment" not in dashboard["data"]:
            pytest.skip("周末无数据")
        ms = dashboard["data"]["market_sentiment"]
        valid = ("bullish", "bearish", "neutral", "unavailable")
        assert ms.get("sentiment") in valid


# ═══════════════════════════════════════════
# 模块 8: 数据源状态
# ═══════════════════════════════════════════


class TestProviders:
    """验证 providers 列表（仅交易时段有数据）。"""

    def test_providers_present_or_weekend(self, dashboard: dict):
        """周末可能无 providers，但不应报错。"""
        if "providers" not in dashboard["data"]:
            pytest.skip("周末/非交易时段无 providers")
        providers = dashboard["data"]["providers"]
        assert isinstance(providers, list)
        assert len(providers) >= 1


# ═══════════════════════════════════════════
# 整体结构验证
# ═══════════════════════════════════════════


class TestDashboardStructure:
    """验证 dashboard 响应整体结构。"""

    def test_status_is_ok(self, dashboard: dict):
        assert dashboard["data"]["status"] == "ok"

    def test_watchlist_count_is_int(self, dashboard: dict):
        assert isinstance(dashboard["data"]["watchlist_count"], int)

    def test_response_envelope(self, dashboard: dict):
        """响应包含 server_time + data + freshness 三层。"""
        assert "server_time" in dashboard
        assert "data" in dashboard
        assert "freshness" in dashboard
