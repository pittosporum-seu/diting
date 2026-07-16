"""谛听 · 东方财富 mx-data 数据提供者

基于妙想金融数据 API，使用自然语言查询获取行情数据。
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

# mx-data skill 路径不在 PYTHONPATH 中，动态添加
_MX_SKILL_DIR = Path.home() / ".hermes/skills/openclaw-imports/mx-data"
if str(_MX_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_MX_SKILL_DIR))

from mx_data import MXData  # noqa: E402

from ...infra.errors import DataUnavailableError  # noqa: E402
from ...infra.logging_config import get_logger  # noqa: E402
from ...schema import HistoricalData, RealtimeQuote  # noqa: E402
from .base import DataProvider  # noqa: E402

logger = get_logger(__name__)

# ── 查询模板 ──────────────────────────────────────

_REALTIME_FIELDS = (
    "收盘价", "涨跌幅", "开盘价", "最高价", "最低价",
    "成交量", "成交额", "市盈率", "市净率", "总市值",
)

_HISTORICAL_FIELDS = (
    "每日收盘价", "开盘价", "最高价", "最低价", "成交量",
)


class MxDataProvider(DataProvider):
    """东方财富 mx-data 数据源。

    通过自然语言查询获取金融数据，返回规范化后的 @dataclass。
    """

    @property
    def name(self) -> str:
        return "mx_data"

    @property
    def priority(self) -> int:
        return 20  # 第三优先级（需 API Key，在 ashare/east_money 之后）

    def __init__(self, api_key: str | None = None):
        self._client: MXData | None = None
        self._api_key = api_key

    def _get_client(self) -> MXData:
        if self._client is None:
            try:
                self._client = MXData(api_key=self._api_key)
            except ValueError as e:
                raise DataUnavailableError(
                    f"mx-data: {e}"
                ) from e
        return self._client

    # ── 接口实现 ──────────────────────────────────

    def health_check(self) -> bool:
        try:
            client = self._get_client()
            client.query("沪深300指数最新点位")
            return True
        except Exception:
            return False

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        if not symbols:
            return {}

        # 限制每批最多 4 只，避免数据截断
        results: dict[str, RealtimeQuote] = {}
        batch_size = 4
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            names = " ".join(batch)
            fields = " ".join(_REALTIME_FIELDS)
            query = f"{names} {fields}"
            results.update(self._query_realtime(query, batch))

        return results

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        fields = " ".join(_HISTORICAL_FIELDS)
        query = (
            f"{symbol} {fields} "
            f"{start.strftime('%Y-%m-%d')} 至 {end.strftime('%Y-%m-%d')}"
        )
        return self._query_historical(query, symbol, start, end)

    # ── 内部方法 ──────────────────────────────────

    def _query_realtime(
        self, query: str, symbols: list[str]
    ) -> dict[str, RealtimeQuote]:
        """查询实时行情并映射到 RealtimeQuote"""
        try:
            client = self._get_client()
            raw = client.query(query)
            tables, _, _, error = MXData.parse_result(raw)
        except Exception as e:
            logger.error(
                "mx_data.realtime.failed", query=query, error=str(e)
            )
            raise DataUnavailableError(f"mx-data realtime: {e}") from e

        if error:
            logger.warning("mx_data.realtime.parse_error", error=error)

        results: dict[str, RealtimeQuote] = {}
        now = datetime.now()

        for table in tables:
            rows = table.get("rows", [])
            fieldnames = table.get("fieldnames", [])
            if not rows:
                continue

            for row in rows:
                symbol = self._extract_symbol(row, fieldnames, symbols, table)
                if not symbol or symbol in results:
                    continue

                try:
                    quote = self._row_to_quote(row, fieldnames, symbol, now)
                    results[symbol] = quote
                except (KeyError, ValueError, TypeError) as e:
                    logger.warning(
                        "mx_data.realtime.row_failed",
                        symbol=symbol,
                        error=str(e),
                    )

        return results

    def _query_historical(
        self, query: str, symbol: str, start: date, end: date
    ) -> HistoricalData:
        """查询历史行情并映射到 HistoricalData"""
        import pandas as pd

        try:
            client = self._get_client()
            raw = client.query(query)
            tables, _, _, error = MXData.parse_result(raw)
        except Exception as e:
            logger.error(
                "mx_data.historical.failed",
                query=query,
                error=str(e),
            )
            raise DataUnavailableError(f"mx-data historical: {e}") from e

        if error:
            logger.warning("mx_data.historical.parse_error", error=error)

        if not tables:
            raise DataUnavailableError(
                f"mx-data: no historical data for {symbol}"
            )

        # 取第一个表
        table = tables[0]
        rows = table.get("rows", [])
        fieldnames = table.get("fieldnames", [])

        if not rows:
            raise DataUnavailableError(
                f"mx-data: empty historical data for {symbol}"
            )

        # 构建 DataFrame
        data: dict[str, list] = {}
        for row in rows:
            for col in fieldnames:
                data.setdefault(col, []).append(row.get(col, ""))

        df = pd.DataFrame(data)

        # 清理日期列
        if "date" in df.columns:
            df["date"] = df["date"].astype(str).str.replace(r"\(.*?\)", "", regex=True)

        # 清理数值列中的单位后缀 —— 先转 object 避免 StringDtype 无法赋值
        num_cols = [c for c in df.columns if c != "date"]
        df[num_cols] = df[num_cols].astype(object)
        unit_map = {
            "亿股": 1e8, "万股": 1e4, "股": 1,
            "亿元": 1e8, "万元": 1e4,
        }
        for col in df.columns:
            if col == "date":
                continue
            series = df[col].astype(str)
            # 检测是否含单位
            has_unit = any(u in "".join(series) for u in unit_map)
            if has_unit:
                for unit, mult in unit_map.items():
                    mask = series.str.contains(unit, regex=False, na=False)
                    if mask.any():
                        cleaned = (
                            series[mask]
                            .str.replace(unit, "", regex=False)
                            .str.replace("元", "", regex=False)
                            .str.replace(",", "", regex=False)
                        )
                        df.loc[mask, col] = pd.to_numeric(cleaned, errors="coerce") * mult
            else:
                df[col] = pd.to_numeric(
                    series.str.replace("元", "", regex=False)
                    .str.replace(",", "", regex=False),
                    errors="coerce",
                )

        return HistoricalData(
            symbol=symbol,
            df=df,
            columns=list(df.columns),
            start_date=start,
            end_date=end,
        )

    # ── 行解析辅助 ────────────────────────────────

    @staticmethod
    def _extract_symbol(
        row: dict,
        fieldnames: list[str],
        requested: list[str],
        table: dict | None = None,
    ) -> str | None:
        """从行数据中提取股票代码。

        mx-data 的 parsed table 中 fieldnames 不包含股票代码，
        代码在 entityName（如 "立讯精密 (002475.SZ)"）中但 parse_result 不保留。
        因此优先从已知的 requested 列表按顺序映射。
        """
        import re

        # 单 symbol：直接返回
        if len(requested) == 1:
            return requested[0]

        # 多 symbol：尝试从 sheet_name 提取 6 位代码
        if table:
            sheet = str(table.get("sheet_name", ""))
            m = re.search(r"(\d{6})", sheet)
            if m:
                code = m.group(1)
                if code in requested:
                    return code

        # 最后尝试从 row 的字段值中匹配
        for col in fieldnames:
            val = str(row.get(col, ""))
            for sym in requested:
                if sym in val:
                    return sym

        return None

    @staticmethod
    def _row_to_quote(
        row: dict, fieldnames: list[str], symbol: str, now: datetime
    ) -> RealtimeQuote:
        """将一行数据映射为 RealtimeQuote"""

        def get_val(*keys: str) -> str:
            for k in keys:
                for fn in fieldnames:
                    if k in fn:
                        return str(row.get(fn, "")).replace("元", "")
            return ""

        def to_float(*keys: str) -> float:
            v = get_val(*keys)
            if not v or v in ("-", "--", "nan"):
                return 0.0
            try:
                return float(v.replace("%", "").replace(",", ""))
            except ValueError:
                return 0.0

        def to_int(*keys: str) -> int:
            v = get_val(*keys)
            if not v or v in ("-", "--", "nan"):
                return 0
            try:
                return int(float(v.replace(",", "")))
            except ValueError:
                return 0

        price = to_float("最新价", "收盘价")
        change_pct = to_float("涨跌幅")
        open_price = to_float("今开", "开盘价")
        high = to_float("最高", "最高价")
        low = to_float("最低", "最低价")
        volume = to_int("成交量")
        turnover = to_float("成交额")

        if price == 0:
            raise ValueError(f"No price data for {symbol}")

        return RealtimeQuote(
            symbol=symbol,
            name=symbol,  # mx-data 后续可补全名称
            price=price,
            change_pct=change_pct,
            open=open_price if open_price else price,
            high=high if high else price,
            low=low if low else price,
            volume=volume,
            turnover=turnover,
            pe=to_float("市盈率") if to_float("市盈率") else None,
            pb=to_float("市净率") if to_float("市净率") else None,
            total_mv=to_float("总市值") if to_float("总市值") else None,
            timestamp=now,
            source=None,  # 后续由 Repository 标注
        )
