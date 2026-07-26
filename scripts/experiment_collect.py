"""实验采集：一次性收集 ground truth（全量 6 引擎分）+ 所有快速指标。

设计原则（减少 AI 调用）：
- 每只股票只调一次 analyze_stock(force=True)，同时拿到 ground truth 和 signals
- 所有数据一次性存盘 experiment/data.csv
- 之后的相关性/回归/组合尝试都在 experiment_analyze.py 里纯计算，不再调 AI

用法：
  export AI_API_KEY=<xiaomi key>
  python scripts/experiment_collect.py [--limit 60] [--sleep 2]
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "src")

# ── 强制配置 AI（绕过 DB 设置，实验专用）──────────────
from diting.ai import client as ai_client

ai_client._llm = ai_client.AIClient(
    model=os.environ.get("AI_MODEL", "openai/mimo-v2.5"),
    api_key=os.environ.get("AI_API_KEY", ""),
    api_base=os.environ.get("AI_BASE_URL", "https://api.xiaomimimo.com/v1"),
)

from diting.cache import CacheManager  # noqa: E402
from diting.web.services.stock import StockService  # noqa: E402

ENGINE_NAMES = ["wyckoff", "buffett", "can_slim", "volume_profile", "vmd_rsi", "verdict"]
AI_ENGINES = {"wyckoff", "buffett", "can_slim"}


def select_samples(stock_service: StockService, limit: int) -> list[str]:
    """选样本：自选股 + 按涨跌幅分桶分层抽样（覆盖涨/跌/横盘）。"""
    codes: list[str] = []
    seen: set[str] = set()

    # 1. 自选股
    try:
        from diting.config import Config

        for s in Config().load_watchlist(validate=False):
            c = s.get("code")
            if c and c not in seen and c[0] in "0236":
                seen.add(c)
                codes.append(c)
    except Exception:
        pass

    # 2. 从 market_snapshot 按涨跌幅分桶抽样
    try:
        cm = stock_service._get_cache_mgr()
        import sqlite3

        conn = sqlite3.connect(cm.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT code, change_pct FROM market_snapshot WHERE price > 2"
        ).fetchall()
        conn.close()

        buckets = {"big_up": [], "up": [], "flat": [], "down": [], "big_down": []}
        for r in rows:
            c, pct = r["code"], r["change_pct"] or 0.0
            if c in seen:
                continue
            # 只留沪深 A 股（0/2/3/6 开头），排除 ETF/基金/北交所
            if not c or c[0] not in "0236":
                continue
            if pct > 4:
                buckets["big_up"].append(c)
            elif pct > 1:
                buckets["up"].append(c)
            elif pct >= -1:
                buckets["flat"].append(c)
            elif pct >= -4:
                buckets["down"].append(c)
            else:
                buckets["big_down"].append(c)

        # 每桶均匀抽样
        remaining = limit - len(codes)
        per_bucket = max(1, remaining // len(buckets))
        for name, bucket in buckets.items():
            # 等间距抽样保证分布
            if not bucket:
                continue
            step = max(1, len(bucket) // per_bucket)
            picked = bucket[::step][:per_bucket]
            for c in picked:
                if c not in seen:
                    seen.add(c)
                    codes.append(c)
    except Exception as e:
        print(f"[warn] market_snapshot 抽样失败: {e}")

    return codes[:limit]


def compute_fast_indicators(quote, sig: dict | None) -> dict:
    """从实时行情 + 技术信号计算所有快速指标（无需 AI）。"""
    ind: dict = {}
    # 来自实时行情
    price = getattr(quote, "price", None) or 0.0
    open_p = getattr(quote, "open", None) or 0.0
    high = getattr(quote, "high", None) or 0.0
    low = getattr(quote, "low", None) or 0.0

    ind["change_pct"] = getattr(quote, "change_pct", None)
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
    # 开盘强度 %（收盘 vs 开盘）
    if open_p and price:
        ind["open_strength"] = round((price - open_p) / open_p * 100, 3)
    else:
        ind["open_strength"] = None
    ind["pe"] = getattr(quote, "pe", None)

    # 来自技术信号
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
    # 均线多头排列得分：ma5>ma20 +1, ma20>ma60 +1, price>ma5 +1（0~3）
    align = 0
    if ma5 and ma20 and ma5 > ma20:
        align += 1
    if ma20 and ma60 and ma20 > ma60:
        align += 1
    if price and ma5 and price > ma5:
        align += 1
    ind["ma_alignment"] = align
    # 价格相对 MA20 偏离 %
    if price and ma20:
        ind["price_vs_ma20"] = round((price - ma20) / ma20 * 100, 3)
    else:
        ind["price_vs_ma20"] = None

    return ind


def collect_one(stock_service: StockService, code: str) -> dict | None:
    """采集一只股票：ground truth（共识+各引擎分）+ 快速指标。"""
    try:
        resp = stock_service.analyze_stock(code, force=True)
    except Exception as e:
        print(f"[skip] {code} analyze 失败: {e}")
        return None

    if resp.error:
        print(f"[skip] {code} error: {resp.error}")
        return None

    # ground truth：共识分 + 各引擎分
    row = {
        "code": code,
        "name": resp.name,
        "consensus_score": resp.score,
        "n_engines": len(resp.engine_scores),
    }
    eng_by_name = {e.engine_name: e.score for e in resp.engine_scores}
    for en in ENGINE_NAMES:
        row[f"eng_{en}"] = eng_by_name.get(en)
    row["has_ai"] = 1 if any(en in eng_by_name for en in AI_ENGINES) else 0

    # 快速指标
    quote = stock_service.get_realtime(code)
    sig = resp.signals_summary
    inds = compute_fast_indicators(quote, sig)
    row.update(inds)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=60, help="样本数量")
    parser.add_argument("--sleep", type=float, default=2.0, help="每只间隔秒数（限流）")
    parser.add_argument("--out", default="experiment/data.csv", help="输出 CSV")
    args = parser.parse_args()

    cm = CacheManager()
    stock_service = StockService(cache_mgr=cm)

    samples = select_samples(stock_service, args.limit)
    print(f"样本数: {len(samples)}")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = []
    for i, code in enumerate(samples):
        print(f"[{i + 1}/{len(samples)}] {code} ...", end=" ", flush=True)
        row = collect_one(stock_service, code)
        if row:
            rows.append(row)
            print(
                f"consensus={row['consensus_score']} engines={row['n_engines']} "
                f"has_ai={row['has_ai']}"
            )
        else:
            print("skipped")
        time.sleep(args.sleep)

    if not rows:
        print("无有效样本")
        return

    # 写 CSV（所有列的并集）
    fieldnames = list(rows[0].keys())
    for r in rows:
        for k in r.keys():
            if k not in fieldnames:
                fieldnames.append(k)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    n_with_ai = sum(1 for r in rows if r.get("has_ai"))
    print(f"\n完成: {len(rows)} 只样本 → {out_path}")
    print(f"含 AI 引擎分析的: {n_with_ai}/{len(rows)}")


if __name__ == "__main__":
    main()
