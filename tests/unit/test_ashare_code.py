"""ashare 指数代码转换 + 扫描北交所过滤测试。"""

from __future__ import annotations

from src.diting.data.providers.ashare import _to_sina_code


class TestToSinaCode:
    def test_sh_suffix(self):
        """上证指数 000001.SH → sh000001（区别于平安银行）。"""
        assert _to_sina_code("000001.SH") == "sh000001"

    def test_sz_suffix(self):
        assert _to_sina_code("399001.SZ") == "sz399001"

    def test_bj_suffix(self):
        assert _to_sina_code("830799.BJ") == "bj830799"

    def test_suffix_case_insensitive(self):
        assert _to_sina_code("000001.sh") == "sh000001"

    def test_pure_sh_stock(self):
        """6 开头 → sh。"""
        assert _to_sina_code("600519") == "sh600519"

    def test_pure_sz_stock(self):
        """0 开头 → sz。"""
        assert _to_sina_code("002475") == "sz002475"

    def test_pure_chinext(self):
        """3 开头（创业板）→ sz。"""
        assert _to_sina_code("300750") == "sz300750"

    def test_pure_bj_stock(self):
        """8 开头 → bj。"""
        assert _to_sina_code("830799") == "bj830799"

    def test_index_vs_stock_disambiguation(self):
        """000001.SH（上证指数）与 000001（平安银行）区分。"""
        assert _to_sina_code("000001.SH") == "sh000001"
        assert _to_sina_code("000001") == "sz000001"


class TestScanBseFilter:
    """扫描应排除北交所股票（免费源抓不到）。"""

    def test_filter_keeps_sh_sz(self):
        codes = ["600519", "002475", "300750", "000001"]
        kept = [c for c in codes if c and c[0] in "0236"]
        assert kept == ["600519", "002475", "300750", "000001"]

    def test_filter_excludes_bse(self):
        codes = ["600519", "920001", "830799", "430047", "002475"]
        kept = [c for c in codes if c and c[0] in "0236"]
        assert "920001" not in kept  # 北交所新代码
        assert "830799" not in kept  # 北交所
        assert "430047" not in kept  # 北交所
        assert "600519" in kept
        assert "002475" in kept
