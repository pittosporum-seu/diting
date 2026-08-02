"""谛听 · 基础价格/估值上下文提供者"""

from __future__ import annotations

import numpy as np

from .base import ContextProvider


class PriceBasicProvider(ContextProvider):
    """基础价格摘要：现价、涨跌、估值、区间、近期走势。"""

    @property
    def name(self) -> str:
        return "price_basic"

    def provide(self, code: str, close: np.ndarray, quote=None) -> str | None:
        if len(close) < 30:
            return None

        price = close[-1]
        chg = 0.0
        pe = "N/A"
        pb = "N/A"
        mv = "N/A"
        stock_name = code

        if quote:
            chg = getattr(quote, "change_pct", 0) or 0
            _pe = getattr(quote, "pe", None)
            pe = f"{_pe:.1f}" if _pe else "N/A"
            _pb = getattr(quote, "pb", None)
            pb = f"{_pb:.2f}" if _pb else "N/A"
            _mv = getattr(quote, "total_mv", None)
            mv = f"{_mv / 1e8:.0f}亿" if _mv else "N/A"
            stock_name = getattr(quote, "name", code) or code

        chg20 = (close[-1] / close[-20] - 1) * 100 if len(close) >= 20 else 0
        recent5 = [round(x, 2) for x in close[-5:].tolist()]
        avg_vol = getattr(quote, "volume", 0) if quote else 0

        return (
            f"[{code} {stock_name}] 现价{price:.2f} "
            f"涨跌{chg:.1f}% PE={pe} PB={pb} 总市值{mv} | "
            f"{len(close)}日 区间{close.min():.2f}-{close.max():.2f} "
            f"近20日{chg20:+.1f}% 近5日{recent5} 均量{avg_vol:.0f}"
        )
