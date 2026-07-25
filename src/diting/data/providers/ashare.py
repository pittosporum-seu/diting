"""谛听 · Ashare 免费数据提供者

基于新浪/腾讯公开行情接口，无需 API Key。
内联实现，零额外依赖（仅 requests）。
"""

from __future__ import annotations

import re
from datetime import date, datetime

import requests

from ...infra.errors import DataUnavailableError
from ...infra.logging_config import get_logger
from ...schema import HistoricalData, RealtimeQuote
from .base import DataProvider

logger = get_logger(__name__)

# ── 内部常量 ──────────────────────────────────────

_SINA_API = "https://hq.sinajs.cn/list="
_HEADERS = {"Referer": "https://finance.sina.com.cn"}


def _to_sina_code(code: str) -> str:
    """将代码转为新浪格式。

    支持带交易所后缀的代码（如上证指数 000001.SH → sh000001）。
    纯数字代码按首位推断：sz: 0/2/3 开头，sh: 6 开头，bj: 4/8 开头。
    指数代码（如上证指数 000001）需显式带 .SH 后缀以区别于同名股票（平安银行）。
    """
    # 优先处理交易所后缀
    upper = code.upper()
    if upper.endswith(".SH"):
        return f"sh{code[:-3]}"
    if upper.endswith(".SZ"):
        return f"sz{code[:-3]}"
    if upper.endswith(".BJ"):
        return f"bj{code[:-3]}"
    # 纯数字代码按首位推断
    if code.startswith(("0", "2", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sh{code}"


def _parse_realtime_line(line: str) -> dict | None:
    """解析新浪实时行情单行数据。

    返回字段字典，解析失败返回 None。
    """
    try:
        # 格式: var hq_str_sh600519="name,open,close,high,low,volume,amount,..."
        match = re.search(r'="(.*)"', line)
        if not match:
            return None
        fields = match.group(1).split(",")
        if len(fields) < 9:
            return None
        return {
            "name": fields[0],
            "open": fields[1],
            "close": fields[2],
            "price": fields[3],
            "high": fields[4],
            "low": fields[5],
            "volume": fields[8],
            "amount": fields[9] if len(fields) > 9 else "0",
        }
    except (IndexError, ValueError):
        return None


def _fetch_tencent_daily(code: str, count: int = 500) -> list[dict] | None:
    """从腾讯接口拉取日线数据。

    Returns:
        [{"date": "...", "open": ..., "close": ..., "high": ..., "low": ...,
          "volume": ..., "amount": ...}, ...]
    """
    url = (
        f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={code},day,,,{count},qfq"
    )
    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        klines = data.get("data", {}).get(code, {}).get("qfqday", [])
        if not klines and "day" in data.get("data", {}).get(code, {}):
            klines = data["data"][code].get("day", [])
        result = []
        for row in klines:
            if isinstance(row, dict):
                result.append({
                    "date": str(row.get("date", "")),
                    "open": float(row.get("open", 0) or 0),
                    "close": float(row.get("close", 0) or 0),
                    "high": float(row.get("high", 0) or 0),
                    "low": float(row.get("low", 0) or 0),
                    "volume": int(float(row.get("volume", 0) or 0)),
                    "amount": float(row.get("amount", 0) or 0),
                })
            elif len(row) >= 6:
                result.append({
                    "date": str(row[0]),
                    "open": float(row[1]) if not isinstance(row[1], dict) else 0,
                    "close": float(row[2]) if not isinstance(row[2], dict) else 0,
                    "high": float(row[3]) if not isinstance(row[3], dict) else 0,
                    "low": float(row[4]) if not isinstance(row[4], dict) else 0,
                    "volume": int(float(row[5]) if not isinstance(row[5], dict) else 0),
                    "amount": (
                        float(row[6])
                        if len(row) > 6 and not isinstance(row[6], dict)
                        else 0.0
                    ),
                })
        return result if result else None
    except Exception as e:
        logger.warning("ashare.tencent.daily.failed", code=code, error=str(e))
        return None


class AshareProvider(DataProvider):
    """新浪/腾讯免费数据源。

    无需 API Key，作为纯免费的兜底方案。
    实时行情走新浪接口，日线走腾讯接口。
    """

    @property
    def name(self) -> str:
        return "ashare"

    @property
    def priority(self) -> int:
        return 6  # 免费可用，速度快，次于 east_money（不提供 PE/PB）

    def __init__(self):
        self._available: bool | None = None

    # ── 接口实现 ──────────────────────────────────

    def health_check(self) -> bool:
        if self._available is None:
            try:
                resp = requests.get(
                    f"{_SINA_API}sh600519",
                    headers=_HEADERS,
                    timeout=5,
                )
                self._available = resp.status_code == 200 and len(resp.text) > 50
            except Exception:
                self._available = False
        return self._available

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        """获取实时行情，每批最多 50 只，分批请求合并结果。"""
        if not symbols:
            return {}

        batch_size = 50
        results: dict[str, RealtimeQuote] = {}
        now = datetime.now()

        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i + batch_size]
            sina_codes = [_to_sina_code(s) for s in batch]
            query = ",".join(sina_codes)
            url = f"{_SINA_API}{query}"

            try:
                resp = requests.get(url, headers=_HEADERS, timeout=10)
                resp.raise_for_status()
            except Exception as e:
                logger.warning(
                    "ashare.batch_failed",
                    batch_start=i,
                    batch_size=len(batch),
                    error=str(e),
                )
                continue  # 一批失败不影响其他批次

            for line in resp.text.strip().split("\n"):
                if not line.strip():
                    continue
                parsed = _parse_realtime_line(line)
                if parsed is None:
                    continue

                # 从 URL 匹配代码映射回来
                code = None
                for sym in batch:
                    sina = _to_sina_code(sym)
                    if sina in line:
                        code = sym
                        break

                if not code or code in results:
                    continue

                try:
                    price = float(parsed["price"])
                    pre_close = float(parsed["close"])
                    change_pct = (
                        ((price - pre_close) / pre_close * 100) if pre_close else 0.0
                    )

                    quote = RealtimeQuote(
                        symbol=code,
                        name=parsed["name"],
                        price=price,
                        change_pct=change_pct,
                        open=float(parsed["open"] or 0),
                        high=float(parsed["high"] or 0),
                        low=float(parsed["low"] or 0),
                        volume=int(float(parsed["volume"] or 0)),
                        turnover=float(parsed["amount"] or 0),
                        timestamp=now,
                    )
                    results[code] = quote
                except (ValueError, TypeError) as e:
                    logger.warning(
                        "ashare.realtime.row_failed", symbol=code, error=str(e)
                    )

        return results

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        sina_code = _to_sina_code(symbol)
        klines = _fetch_tencent_daily(sina_code, count=2000)

        if not klines:
            raise DataUnavailableError(
                f"ashare: no historical data for {symbol}"
            )

        import pandas as pd

        # Filter by date range
        filtered = []
        for row in klines:
            try:
                d = date.fromisoformat(row["date"])
                if start <= d <= end:
                    filtered.append(row)
            except (ValueError, TypeError):
                continue

        if not filtered:
            raise DataUnavailableError(
                f"ashare: no historical data for {symbol} in range {start}..{end}"
            )

        df = pd.DataFrame(filtered)

        return HistoricalData(
            symbol=symbol,
            df=df,
            columns=list(df.columns),
            start_date=start,
            end_date=end,
        )
