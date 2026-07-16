"""#7 数据提供者测试：mx-data + akshare + cache"""

from unittest.mock import patch

from src.diting.data.cache import CacheLayer
from src.diting.data.providers.akshare import AkShareProvider
from src.diting.data.providers.base import DataProvider
from src.diting.data.providers.mx_data import MxDataProvider

# ═══════════════════════════════════════════
# CacheLayer
# ═══════════════════════════════════════════


class TestCacheLayer:
    def test_set_and_get(self):
        cache = CacheLayer(max_size=10)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_expired(self):
        cache = CacheLayer(max_size=10)
        cache.set("key1", "value1", ttl=0)  # 立即过期
        assert cache.get("key1") is None

    def test_miss(self):
        cache = CacheLayer(max_size=10)
        assert cache.get("nonexistent") is None

    def test_lru_eviction(self):
        cache = CacheLayer(max_size=3)
        for i in range(5):
            cache.set(str(i), f"value{i}")
        # 只有最近3个保留
        assert cache.get("0") is None
        assert cache.get("1") is None
        assert cache.get("2") == "value2"
        assert cache.get("4") == "value4"

    def test_clear(self):
        cache = CacheLayer(max_size=10)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_lru_access_keeps_alive(self):
        cache = CacheLayer(max_size=3)
        cache.set("0", "val0")
        cache.set("1", "val1")
        cache.set("2", "val2")
        # 访问 "0"，把它移到末尾
        cache.get("0")
        # 插入新值，淘汰最老的 "1"
        cache.set("3", "val3")
        assert cache.get("0") == "val0"  # 被访问过，保留
        assert cache.get("1") is None    # 最老，被淘汰
        assert cache.get("2") == "val2"
        assert cache.get("3") == "val3"


# ═══════════════════════════════════════════
# MxDataProvider (mock API)
# ═══════════════════════════════════════════


class TestMxDataProvider:
    """mx-data 提供者单元测试（mock API，不需要真实 apikey）"""

    def test_name_and_priority(self):
        p = MxDataProvider(api_key="fake")
        assert p.name == "mx_data"
        assert p.priority == 20

    def test_health_check_requires_valid_key(self):
        """无有效 apikey 时 health_check 返回 False。"""
        import os
        if os.getenv("MX_APIKEY"):
            p = MxDataProvider()
            assert p.health_check() is True
        else:
            with patch("src.diting.data.providers.mx_data.MXData") as mock_mx:
                mock_mx.side_effect = ValueError("invalid api key")
                p = MxDataProvider(api_key="invalid_key")
                assert p.health_check() is False

    def test_fetch_realtime_with_mock(self):
        # 直接构建 parse 后的 mock_tables，测试 _row_to_quote
        mock_tables = [{
            "sheet_name": "002475",
            "rows": [{
                "最新价": "70.40",
                "涨跌幅": "2.10",
                "今开": "69.00",
                "最高": "71.00",
                "最低": "68.50",
                "成交量": "10000000",
                "成交额": "700000000",
                "市盈率": "25.5",
                "市净率": "3.2",
                "总市值": "150000000000",
            }],
            "fieldnames": [
                "最新价", "涨跌幅", "今开", "最高", "最低",
                "成交量", "成交额", "市盈率", "市净率", "总市值",
            ],
        }]

        # 直接测试 _row_to_quote
        from datetime import datetime

        row = mock_tables[0]["rows"][0]
        fieldnames = mock_tables[0]["fieldnames"]
        quote = MxDataProvider._row_to_quote(
            row, fieldnames, "002475", datetime.now()
        )
        assert quote.symbol == "002475"
        assert quote.price == 70.40
        assert quote.change_pct == 2.10
        assert quote.pe == 25.5
        assert quote.pb == 3.2

    def test_fetch_realtime_empty_symbols(self):
        p = MxDataProvider(api_key="fake")
        results = p.fetch_realtime([])
        assert results == {}


# ═══════════════════════════════════════════
# AkShareProvider
# ═══════════════════════════════════════════


class TestAkShareProvider:
    def test_name_and_priority(self):
        p = AkShareProvider()
        assert p.name == "akshare"
        assert p.priority == 50

    def test_provider_is_instance(self):
        p = AkShareProvider()
        assert isinstance(p, DataProvider)

    def test_fetch_realtime_empty_symbols(self):
        p = AkShareProvider()
        results = p.fetch_realtime([])
        assert results == {}

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_realtime_mocked(self, mock_ak):
        """用 mock akshare 测试数据映射"""
        import pandas as pd

        mock_df = pd.DataFrame([
            {
                "代码": "002475", "名称": "立讯精密",
                "最新价": 70.40, "涨跌幅": 2.10,
                "今开": 69.00, "最高": 71.00, "最低": 68.50,
                "成交量": 10000000, "成交额": 700000000,
                "市盈率-动态": 25.5, "市净率": 3.2,
                "总市值": 150000000000,
            }
        ])
        mock_ak.return_value = mock_df

        p = AkShareProvider()
        results = p.fetch_realtime(["002475"])

        assert "002475" in results
        q = results["002475"]
        assert q.symbol == "002475"
        assert q.name == "立讯精密"
        assert q.price == 70.40
        assert q.pe == 25.5

    @patch("akshare.stock_zh_a_spot_em")
    def test_fetch_realtime_symbol_not_found(self, mock_ak):
        """查询的股票不在 akshare 返回结果中"""
        import pandas as pd

        mock_df = pd.DataFrame([
            {"代码": "603659", "名称": "璞泰来", "最新价": 50.0,
             "涨跌幅": 1.0, "今开": 49.0, "最高": 51.0, "最低": 48.5,
             "成交量": 5000000, "成交额": 250000000,
             "市盈率-动态": 30.0, "市净率": 2.5, "总市值": 50000000000}
        ])
        mock_ak.return_value = mock_df

        p = AkShareProvider()
        results = p.fetch_realtime(["002475"])  # 不在 mock 结果中
        assert "002475" not in results
