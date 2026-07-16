"""谛听 · 东方财富免费数据提供者

基于东方财富公开 HTTP API，无需 API Key，直连可用。
提供实时行情（含 PE/PB/市值）和资金流向数据。
"""

from __future__ import annotations

from datetime import date, datetime

import requests

from ...infra.errors import DataUnavailableError
from ...infra.logging_config import get_logger
from ...schema import FundFlow, HistoricalData, RealtimeQuote
from .base import DataProvider

logger = get_logger(__name__)

# ── 内部常量 ──────────────────────────────────────────────

_REALTIME_API = "https://push2.eastmoney.com/api/qt/stock/get"
_FUND_FLOW_API = "https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get"
_REQUEST_TIMEOUT = 10
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": _USER_AGENT,
    "Referer": "https://quote.eastmoney.com/",
}


def _to_em_secid(code: str) -> str:
    """将纯数字代码转为东方财富 secid 格式。

    sz: 0/2/3 开头 → 0.{code}，sh: 6 开头 → 1.{code}，
    bj: 4/8 开头 → 0.{code}。
    """
    if code.startswith("6"):
        return f"1.{code}"
    return f"0.{code}"


def _div100(val: str | float | None, default: float = 0.0) -> float:
    """安全除以 100。"""
    try:
        if val is None:
            return default
        v = float(val)
        if str(val).strip() == "-":
            return default
        return v / 100.0
    except (ValueError, TypeError):
        return default


class EastMoneyProvider(DataProvider):
    """东方财富免费数据源。

    无需 API Key，基于东方财富公开 HTTP 接口。
    提供含 PE/PB/市值的实时行情和资金流向数据。
    """

    @property
    def name(self) -> str:
        return "east_money"

    @property
    def priority(self) -> int:
        return 3  # 最高优先级，提供 PE/PB/市值/资金流向（免费直连）

    def __init__(self):
        self._available: bool | None = None

    # ── 健康检查 ──────────────────────────────────────────

    def health_check(self) -> bool:
        if self._available is None:
            try:
                resp = requests.get(
                    _REALTIME_API,
                    params={"secid": "1.600519", "fields": "f43"},
                    headers=_HEADERS,
                    timeout=5,
                )
                self._available = (
                    resp.status_code == 200 and "data" in resp.json()
                )
            except Exception:
                self._available = False
        return self._available

    # ── 实时行情 ──────────────────────────────────────────

    def fetch_realtime(self, symbols: list[str]) -> dict[str, RealtimeQuote]:
        """获取实时行情（含 PE/PB/总市值）。

        每次请求单只股票，逐只获取后合并。
        """
        if not symbols:
            return {}

        results: dict[str, RealtimeQuote] = {}
        now = datetime.now()

        # f20=总市值(亿), f21=流通市值(亿), f58=名称
        fields = (
            "f43,f44,f45,f46,f47,f48,f49,f50,f51,"
            "f52,f55,f57,f58,f60,f20,f21,f116,f117,f162,f167,f168,f170"
        )

        for code in symbols:
            secid = _to_em_secid(code)
            try:
                resp = requests.get(
                    _REALTIME_API,
                    params={"secid": secid, "fields": fields},
                    headers=_HEADERS,
                    timeout=_REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                logger.warning(
                    "east_money.realtime.fetch_failed",
                    code=code,
                    error=str(e),
                )
                continue

            try:
                raw = data.get("data")
                if not raw:
                    logger.warning(
                        "east_money.realtime.empty_data", code=code
                    )
                    continue

                price = _div100(raw.get("f43", 0))
                pre_close = _div100(raw.get("f60", 0))
                change_pct = _div100(raw.get("f170", 0))
                # 如果涨跌幅为 0 但从价格可以算出来，用价格计算
                if change_pct == 0.0 and pre_close > 0 and price > 0:
                    change_pct = (price - pre_close) / pre_close * 100

                pe = _div100(raw.get("f162"))
                pb = _div100(raw.get("f167"))
                # f20=总市值(亿)，优先使用；fallback 到 f116/1e8
                total_mv_float = None
                f20_val = raw.get("f20")
                if f20_val is not None and str(f20_val).strip() not in ("", "-"):
                    try:
                        total_mv_float = float(f20_val)
                    except (ValueError, TypeError):
                        pass
                if total_mv_float is None:
                    f116_val = raw.get("f116")
                    if f116_val is not None and str(f116_val).strip() not in ("", "-"):
                        try:
                            total_mv_float = float(f116_val) / 1e8
                        except (ValueError, TypeError):
                            pass

                name = raw.get("f58", "")

                quote = RealtimeQuote(
                    symbol=code,
                    name=str(name) if name else code,
                    price=price,
                    change_pct=change_pct,
                    open=_div100(raw.get("f46", 0)),
                    high=_div100(raw.get("f44", 0)),
                    low=_div100(raw.get("f45", 0)),
                    volume=int(float(raw.get("f47", 0) or 0)),
                    turnover=float(raw.get("f48", 0) or 0) * 10000,
                    pe=pe if pe > 0 else None,
                    pb=pb if pb > 0 else None,
                    total_mv=total_mv_float,
                    timestamp=now,
                )
                results[code] = quote
            except (ValueError, TypeError, KeyError) as e:
                logger.warning(
                    "east_money.realtime.parse_failed",
                    code=code,
                    error=str(e),
                )

        return results

    # ── 资金流向 ──────────────────────────────────────────

    def fetch_fund_flow(self, symbol: str, day: date | None = None) -> FundFlow:
        """获取个股资金流向。

        从东方财富资金流向日线接口获取最新交易日数据。
        """
        secid = _to_em_secid(symbol)
        fields2 = ",".join(f"f{i}" for i in range(51, 65))
        params: dict = {
            "secid": secid,
            "fields1": "f1,f2,f3,f7",
            "fields2": fields2,
            "lmt": 5,
            "klt": 101,
        }
        try:
            resp = requests.get(
                _FUND_FLOW_API,
                params=params,
                headers=_HEADERS,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(
                "east_money.fund_flow.fetch_failed",
                symbol=symbol,
                error=str(e),
            )
            raise DataUnavailableError(
                f"east_money: fund flow fetch failed for {symbol}: {e}"
            ) from e

        klines = data.get("data", {}).get("klines", [])
        if not klines:
            raise DataUnavailableError(
                f"east_money: no fund flow data for {symbol}"
            )

        # 取最新一行（最近交易日）
        latest = klines[-1]
        if isinstance(latest, str):
            parts = latest.split(",")
        else:
            parts = list(latest)

        if len(parts) < 11:
            raise DataUnavailableError(
                f"east_money: unexpected fund flow format for {symbol}"
            )

        try:
            raw_date = parts[0].strip()
            if len(raw_date) >= 10:
                flow_date = date.fromisoformat(raw_date[:10])
            else:
                flow_date = (day or date.today())

            return FundFlow(
                symbol=symbol,
                date=flow_date,
                main_net_inflow=float(parts[1] or 0),
                super_large_net=float(parts[2] or 0),
                large_net=float(parts[3] or 0),
                medium_net=float(parts[4] or 0),
                small_net=float(parts[5] or 0),
                ddx=float(parts[6] or 0) if len(parts) > 6 else 0.0,
                ddy=float(parts[7] or 0) if len(parts) > 7 else 0.0,
                ddz=float(parts[8] or 0) if len(parts) > 8 else 0.0,
            )
        except (ValueError, TypeError) as e:
            raise DataUnavailableError(
                f"east_money: fund flow parse error for {symbol}: {e}"
            ) from e

    # ── 历史行情（暂不支持）─────────────────────────────

    def fetch_historical(
        self, symbol: str, start: date, end: date
    ) -> HistoricalData:
        """东方财富暂不实现历史日线（已有 ashare/eltdx 覆盖）。"""
        raise DataUnavailableError(
            "east_money does not support historical data"
        )
