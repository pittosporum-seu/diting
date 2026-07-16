"""谛听 · 通达信行情数据提供者（deprecated 参考实现）。

基于 eltdx 包，直连通达信行情服务器获取实时行情和历史日线。
当前数据仓库未集成此 provider；文件仅保留供未来参考。
"""

from __future__ import annotations

from datetime import date, datetime

from ...infra.errors import DataUnavailableError
from ...infra.logging_config import get_logger
from ...schema import HistoricalData, RealtimeQuote
from .base import DataProvider

logger = get_logger(__name__)


class ELtdxProvider(DataProvider):
    """通达信直连数据源。

    通过 eltdx 包直连通达信服务器获取行情数据。
    无需 API Key，延迟低。
    """

    @property
    def name(self) -> str:
        return "eltdx"

    @property
    def priority(self) -> int:
        return 10  # 最高优先级

    def __init__(self):
        self._available: bool | None = None

    # ── 接口实现 ──────────────────────────────────

    def health_check(self) -> bool:
        if self._available is None:
            try:
                from eltdx import TdxClient

                client = TdxClient()
                quotes = client.get_quote("000001")
                self._available = len(quotes) > 0
            except Exception:
                self._available = False
        return self._available

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        if not symbols:
            return {}

        try:
            from eltdx import TdxClient
        except ImportError as e:
            raise DataUnavailableError(f"eltdx not installed: {e}") from e

        try:
            client = TdxClient()
            raw_quotes = client.get_quote(symbols)
        except Exception as e:
            logger.error("eltdx.realtime.failed", symbols=symbols, error=str(e))
            raise DataUnavailableError(f"eltdx realtime: {e}") from e

        results: dict[str, RealtimeQuote] = {}
        now = datetime.now()

        # Batch name lookup: try Sina for names (free, fast)
        def _sina_prefix(s: str) -> str:
            return f"sz{s}" if s.startswith(("0", "2", "3")) else f"sh{s}"
        sina_codes = ",".join(_sina_prefix(s) for s in symbols)
        name_map = {}
        try:
            import requests
            resp = requests.get(
                f"https://hq.sinajs.cn/list={sina_codes}",
                headers={"Referer": "https://finance.sina.com.cn"},
                timeout=5,
            )
            for line in resp.text.strip().split("\n"):
                import re
                m = re.search(r'hq_str_([^=]+)="([^,]+)', line)
                if m:
                    code_raw = m.group(1).replace("sz", "").replace("sh", "")
                    for sym in symbols:
                        if sym in code_raw:
                            name_map[sym] = m.group(2)
                            break
        except Exception:
            pass

        for q in raw_quotes:
            code = getattr(q, "code", "")
            if not code or code in results:
                continue

            try:
                last = float(getattr(q, "last_price", 0) or 0)
                pre_close = float(getattr(q, "pre_close_price", 0) or 0)
                change_pct = (
                    ((last - pre_close) / pre_close * 100) if pre_close else 0.0
                )

                quote = RealtimeQuote(
                    symbol=code,
                    name=name_map.get(code, code),  # Sina name lookup, fallback to code
                    price=last,
                    change_pct=change_pct,
                    open=float(getattr(q, "open_price", 0) or 0),
                    high=float(getattr(q, "high_price", 0) or 0),
                    low=float(getattr(q, "low_price", 0) or 0),
                    volume=int(getattr(q, "total_hand", 0) or 0),
                    turnover=float(getattr(q, "amount", 0) or 0),
                    timestamp=now,
                )
                results[code] = quote
            except (ValueError, TypeError) as e:
                logger.warning(
                    "eltdx.realtime.row_failed", symbol=code, error=str(e)
                )

        return results

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        try:
            from eltdx import TdxClient
        except ImportError as e:
            raise DataUnavailableError(f"eltdx not installed: {e}") from e

        # 计算需要的天数
        days = (end - start).days + 1

        try:
            client = TdxClient()
            ks = client.get_kline("1d", symbol, count=max(days, 1))
        except Exception as e:
            logger.error(
                "eltdx.historical.failed", symbol=symbol, error=str(e)
            )
            raise DataUnavailableError(
                f"eltdx historical {symbol}: {e}"
            ) from e

        if not ks or not ks.bars:
            raise DataUnavailableError(
                f"eltdx: no historical data for {symbol}"
            )

        import pandas as pd

        data: dict[str, list] = {
            "date": [],
            "open": [],
            "close": [],
            "high": [],
            "low": [],
            "volume": [],
            "turnover": [],
        }

        for bar in ks.bars:
            bar_date = getattr(bar, "time", "")
            # eltdx KlineBar.time is a string like "2026-07-07"
            if isinstance(bar_date, str) and len(bar_date) >= 10:
                bar_date = bar_date[:10]
            # Filter by date range
            try:
                d = date.fromisoformat(bar_date)
                if d < start or d > end:
                    continue
            except (ValueError, TypeError):
                pass

            data["date"].append(bar_date)
            data["open"].append(float(getattr(bar, "open", 0) or 0))
            data["close"].append(float(getattr(bar, "close", 0) or 0))
            data["high"].append(float(getattr(bar, "high", 0) or 0))
            data["low"].append(float(getattr(bar, "low", 0) or 0))
            data["volume"].append(int(getattr(bar, "volume_lots", 0) or 0))
            data["turnover"].append(float(getattr(bar, "amount", 0) or 0))

        if not data["date"]:
            raise DataUnavailableError(
                f"eltdx: no historical data for {symbol} in range {start}..{end}"
            )

        df = pd.DataFrame(data)

        return HistoricalData(
            symbol=symbol,
            df=df,
            columns=list(df.columns),
            start_date=start,
            end_date=end,
        )
