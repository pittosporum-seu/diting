"""#7 数据提供者测试：ashare + akshare + cache"""

from unittest.mock import patch

from src.diting.data.cache import CacheLayer
from src.diting.data.providers.akshare import AkShareProvider
from src.diting.data.providers.ashare import AshareProvider
from src.diting.data.providers.base import DataProvider

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
# AshareProvider (免费通用数据源)
# ═══════════════════════════════════════════


class TestAshareProvider:
    """Ashare 提供者单元测试（新浪/腾讯免费接口）"""

    def test_name_and_priority(self):
        p = AshareProvider()
        assert p.name == "ashare"
        assert isinstance(p.priority, int)

    def test_health_check(self):
        """Ashare 无需 API Key，health_check 应返回 True"""
        p = AshareProvider()
        assert p.health_check() is True

    def test_fetch_realtime_empty_symbols(self):
        p = AshareProvider()
        results = p.fetch_realtime([])
        assert results == {}

    def test_provider_is_instance(self):
        p = AshareProvider()
        assert isinstance(p, DataProvider)

    @patch("src.diting.data.providers.ashare.requests.get")
    def test_fetch_realtime_mocked(self, mock_get):
        """用 mock 新浪接口测试数据解析"""
        mock_resp = mock_get.return_value
        mock_resp.status_code = 200
        mock_resp.text = (
            'var hq_str_sz002475="立讯精密,60.00,60.59,62.49,59.60,'
            '75736872,4614732730.86,100,200,300,400,500,600,700,800,'
            '900,1000,1100,1200,1300,1400,1500,1600,1700,1800,1900,'
            '2000,2100,2200,2300,2400,2500,2026-07-25,15:00:00,00";\n'
        )
        mock_resp.encoding = "gbk"

        p = AshareProvider()
        results = p.fetch_realtime(["002475"])

        assert "002475" in results
        q = results["002475"]
        assert q.symbol == "002475"
        assert q.name == "立讯精密"


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
