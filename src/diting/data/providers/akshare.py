"""谛听 · akshare 免费数据提供者

基于 akshare 开源库，作为 mx-data 不可用时的兜底方案。
无需 API Key，但数据质量和速度不如 mx-data。
"""

from __future__ import annotations

import warnings
from datetime import date, datetime

from ...infra.errors import DataUnavailableError
from ...infra.logging_config import get_logger
from ...schema import HistoricalData, RealtimeQuote
from .base import DataProvider

logger = get_logger(__name__)


class AkShareProvider(DataProvider):
    """akshare 免费数据源。

    作为兜底方案，当 mx-data 不可用时自动降级到此。
    数据来源：东方财富/新浪等公开接口。
    """

    @property
    def name(self) -> str:
        return "akshare"

    @property
    def priority(self) -> int:
        return 50  # 中等优先级，mx-data 不可用时启用

    def __init__(self):
        self._available: bool | None = None

    # ── 接口实现 ──────────────────────────────────

    def health_check(self) -> bool:
        if self._available is None:
            try:
                import akshare as ak

                # 快速探活：查一只常见股票
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    df = ak.stock_zh_a_spot_em()
                self._available = not df.empty
            except Exception:
                self._available = False
        return self._available

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        if not symbols:
            return {}

        try:
            import akshare as ak
        except ImportError:
            raise DataUnavailableError("akshare not installed")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.error("akshare.realtime.failed", error=str(e))
            raise DataUnavailableError(f"akshare realtime: {e}") from e

        if df.empty:
            raise DataUnavailableError("akshare returned empty data")

        # akshare 返回的列名（中文），直接按原始列名使用
        # 列名映射: 代码/名称/最新价/涨跌幅/今开/最高/最低/成交量/成交额/...

        results: dict[str, RealtimeQuote] = {}
        now = datetime.now()

        # 筛选请求的股票
        df_filtered = df[df["代码"].isin(symbols)]

        for _, row in df_filtered.iterrows():
            code = str(row.get("代码", ""))
            if not code or code in results:
                continue

            try:
                quote = RealtimeQuote(
                    symbol=code,
                    name=str(row.get("名称", code)),
                    price=float(row.get("最新价", 0) or 0),
                    change_pct=float(row.get("涨跌幅", 0) or 0),
                    open=float(row.get("今开", 0) or 0),
                    high=float(row.get("最高", 0) or 0),
                    low=float(row.get("最低", 0) or 0),
                    volume=int(float(row.get("成交量", 0) or 0)),
                    turnover=float(row.get("成交额", 0) or 0),
                    pe=(
                        float(row["市盈率-动态"])
                        if row.get("市盈率-动态") and row["市盈率-动态"] != "-"
                        else None
                    ),
                    pb=(
                        float(row["市净率"]) if row.get("市净率") and row["市净率"] != "-" else None
                    ),
                    total_mv=(
                        float(row["总市值"]) if row.get("总市值") and row["总市值"] != "-" else None
                    ),
                    timestamp=now,
                )
                results[code] = quote
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(
                    "akshare.realtime.row_failed",
                    symbol=code,
                    error=str(e),
                )

        return results

    def fetch_historical(self, symbol: str, start: date, end: date) -> HistoricalData:
        try:
            import akshare as ak
        except ImportError:
            raise DataUnavailableError("akshare not installed")

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start.strftime("%Y%m%d"),
                    end_date=end.strftime("%Y%m%d"),
                    adjust="qfq",  # 前复权
                )
        except Exception as e:
            logger.error(
                "akshare.historical.failed",
                symbol=symbol,
                error=str(e),
            )
            raise DataUnavailableError(f"akshare historical {symbol}: {e}") from e

        if df is None or df.empty:
            raise DataUnavailableError(f"akshare: no historical data for {symbol}")

        # 标准化列名
        col_rename = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "turnover",
            "振幅": "amplitude",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amount",
            "换手率": "turnover_rate",
        }
        df = df.rename(columns={k: v for k, v in col_rename.items() if k in df.columns})

        return HistoricalData(
            symbol=symbol,
            df=df,
            columns=list(df.columns),
            start_date=start,
            end_date=end,
        )
