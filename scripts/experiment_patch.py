"""补丁脚本：修复 data.csv 中因周末采集导致的缺失/错误快速指标。

策略：
- ground truth（引擎分数）不动
- 从 market_snapshot 取上个交易日的 quote 数据（change_pct, open, high, low, price）
- 重新计算技术信号（修复 macd_histogram bug 后的正确值）
- 重新计算所有快速指标

用法：
  python scripts/experiment_patch.py [--data experiment/data.csv]
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "src")

from diting.cache import CacheManager
from diting.signals.technical import TechnicalCalculator
from diting.web.services.stock import StockService


def load_snapshot_quotes(cm: CacheManager) -> dict[str, dict]:
    """从 market_snapshot 加载所有股票的 quote 数据。"""
    conn = sqlite3.connect(str(cm._path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM market_snapshot").fetchall()
    conn.close()
    result = {}
    for r in rows:
        d = dict(r)
        code = d.get("code", "")
        if code:
            result[code] = d
    return result


def recompute_signals(ss: StockService, code: str) -> dict | None:
    """从历史数据重新计算技术信号（用修复后的 MACD）。"""
    try:
        hist = ss.get_historical(code)
        if hist is None or hist.df is None or len(hist.df) < 20:
            return None
        signals = TechnicalCalculator.compute(hist)
        return {
            "rsi_14": signals.rsi_14,
            "macd_histogram": signals.macd_histogram,
            "kdj_k": signals.kdj_k,
            "kdj_d": signals.kdj_d,
            "kdj_j": signals.kdj_j,
            "bollinger_position": signals.bollinger_position,
            "vwap_deviation": signals.vwap_deviation,
            "volume_ratio": signals.volume_ratio,
            "ma_5": signals.ma_5,
            "ma_20": signals.ma_20,
            "ma_60": signals.ma_60,
        }
    except Exception as e:
        print(f"  [warn] {code} 信号重算失败: {e}")
        return None


def compute_indicators(quote: dict | None, sig: dict | None) -> dict:
    """从 quote + signals 计算快速指标。"""
    ind: dict = {}
    quote = quote or {}
    price = quote.get("price") or 0.0
    open_p = quote.get("open") or 0.0
    high = quote.get("high") or 0.0
    low = quote.get("low") or 0.0

    ind["change_pct"] = quote.get("change_pct")
    # 日内位置 0~1
    if high and low and high > low and price:
        ind["intraday_pos"] = round((price - low) / (high - low), 4)
    else:
        ind["intraday_pos"] = None
    # 振幅 %
    if open_p and high and low:
        ind["amplitude"] = round((high - low) / open_p * 100, 3)
    else:
        ind["amplitude"] = None
    # 开盘强度 %
    if open_p and price:
        ind["open_strength"] = round((price - open_p) / open_p * 100, 3)
    else:
        ind["open_strength"] = None
    ind["pe"] = quote.get("pe")

    # 技术信号
    sig = sig or {}
    ind["rsi_14"] = sig.get("rsi_14")
    ind["macd_histogram"] = sig.get("macd_histogram")
    ind["kdj_k"] = sig.get("kdj_k")
    ind["kdj_d"] = sig.get("kdj_d")
    ind["kdj_j"] = sig.get("kdj_j")
    ind["bollinger_position"] = sig.get("bollinger_position")
    ind["vwap_deviation"] = sig.get("vwap_deviation")
    ind["volume_ratio"] = sig.get("volume_ratio")

    ma5 = sig.get("ma_5")
    ma20 = sig.get("ma_20")
    ma60 = sig.get("ma_60")
    align = 0
    if ma5 and ma20 and ma5 > ma20:
        align += 1
    if ma20 and ma60 and ma20 > ma60:
        align += 1
    if price and ma5 and price > ma5:
        align += 1
    ind["ma_alignment"] = align
    if price and ma20:
        ind["price_vs_ma20"] = round((price - ma20) / ma20 * 100, 3)
    else:
        ind["price_vs_ma20"] = None

    return ind


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="experiment/data.csv")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.exists():
        print(f"[error] {data_path} 不存在")
        return

    # 读现有数据
    with open(data_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)
    print(f"加载 {len(rows)} 行")

    cm = CacheManager()
    ss = StockService(cache_mgr=cm)

    # 加载 market_snapshot
    quotes = load_snapshot_quotes(cm)
    print(f"market_snapshot: {len(quotes)} 只")

    # 逐行补丁
    patched = 0
    for i, row in enumerate(rows):
        code = row["code"]
        print(f"  [{i+1}/{len(rows)}] {code} ...", end=" ")
        quote = quotes.get(code)
        sig = recompute_signals(ss, code)
        inds = compute_indicators(quote, sig)
        # 更新快速指标列
        for k, v in inds.items():
            if k in fieldnames:
                row[k] = v if v is not None else ""
        patched += 1
        print("ok" if sig else "no_sig")

    # 写回
    with open(data_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"补丁完成: {patched} 行已更新 → {data_path}")

    # 验证
    print("\n--- 补丁后数据质量 ---")
    check_cols = [
        "change_pct", "intraday_pos", "amplitude", "open_strength",
        "macd_histogram", "rsi_14", "price_vs_ma20",
    ]
    for c in check_cols:
        vals = [r[c] for r in rows if r.get(c, "").strip()]
        nonzero = [v for v in vals if float(v) != 0.0]
        print(f"  {c:22s}: 非空={len(vals):2d}, 非零={len(nonzero):2d}")


if __name__ == "__main__":
    main()
