"""VMD 周期状态全时段测试（2022-2026）。

合并两段数据，在不同市场阶段（熊市/反弹/牛市/回调）测试 VMD 状态描述。
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from diting.config import Config
Config()

from vmd_ai_context import vmd_cycle_state, format_cycle_context


def main():
    # 合并两段数据
    print("加载数据...")
    df1 = pd.read_csv("experiment/backtest_data/daily_2022_2024.csv")
    df2 = pd.read_csv("experiment/backtest_data/daily_2y.csv")
    df_all = pd.concat([df1, df2], ignore_index=True)
    df_all["date"] = pd.to_datetime(df_all["date"])
    df_all = df_all.drop_duplicates(subset=["code", "date"]).sort_values(["code", "date"])
    print(f"合并: {len(df_all)} 行, {df_all['code'].nunique()} 只, "
          f"{df_all['date'].min().date()} ~ {df_all['date'].max().date()}")

    # 按股票分组
    data = {}
    for code, group in df_all.groupby("code"):
        c = np.asarray(group["close"], dtype=float)
        dates = group["date"].tolist()
        if len(c) >= 300:
            data[code] = (c, dates)

    n_stocks = len(data)
    n_days = max(len(v[0]) for v in data.values())
    print(f"有效: {n_stocks} 只, 最长 {n_days} 天\n")

    # 选几个代表性时间点（每隔 ~100 天取一个）
    WINDOW = 250
    code_list = list(data.keys())[:100]  # 取前 100 只

    # 找公共时间点
    min_len = min(len(data[c][0]) for c in code_list)
    test_points = list(range(WINDOW, min_len - 20, 100))
    print(f"测试时间点: {len(test_points)} 个 (每100天)")
    print(f"股票: {len(code_list)} 只\n")

    # 在每个时间点，统计周期状态分布
    print("=" * 90)
    print(f"{'时间点':>6} {'日期':>12} | {'趋势↑':>5} {'趋势↓':>5} {'趋势→':>5} | "
          f"{'半年↑':>5} {'半年↓':>5} | {'月度↑':>5} {'月度↓':>5} | {'共振↑':>5} {'共振↓':>5}")
    print("-" * 90)

    for t in test_points:
        trend_up, trend_down, trend_flat = 0, 0, 0
        half_up, half_down = 0, 0
        month_up, month_down = 0, 0
        reso_up, reso_down = 0, 0
        total = 0

        # 取日期
        sample_date = data[code_list[0]][1][t] if t < len(data[code_list[0]][1]) else "?"
        date_str = str(sample_date)[:10] if hasattr(sample_date, 'strftime') else str(sample_date)[:10]

        for code in code_list:
            close, dates = data[code]
            if t >= len(close) or t < WINDOW:
                continue
            seg = close[t - WINDOW + 1: t + 1]
            state = vmd_cycle_state(seg, K=8, alpha=2000, tol=1e-5)
            if not state:
                continue
            total += 1

            # 趋势
            td = state.get("trend_dir", "→")
            if td == "↑":
                trend_up += 1
            elif td == "↓":
                trend_down += 1
            else:
                trend_flat += 1

            # 半年周期 (cycles[0])
            cycles = state.get("cycles", [])
            if len(cycles) > 0:
                if cycles[0]["dir"] == "↑":
                    half_up += 1
                elif cycles[0]["dir"] == "↓":
                    half_down += 1

            # 月度 (cycles[1])
            if len(cycles) > 1:
                if cycles[1]["dir"] == "↑":
                    month_up += 1
                elif cycles[1]["dir"] == "↓":
                    month_down += 1

            # 共振
            if len(cycles) >= 2:
                if cycles[0]["dir"] == "↑" and cycles[1]["dir"] == "↑":
                    reso_up += 1
                elif cycles[0]["dir"] == "↓" and cycles[1]["dir"] == "↓":
                    reso_down += 1

        if total > 0:
            print(f"  t={t:>3} {date_str:>12} | "
                  f"{trend_up:>4}  {trend_down:>4}  {trend_flat:>4} | "
                  f"{half_up:>4}  {half_down:>4} | "
                  f"{month_up:>4}  {month_down:>4} | "
                  f"{reso_up:>4}  {reso_down:>4}  "
                  f"(n={total})")

    # 打印几个具体例子（不同时间点）
    print(f"\n{'='*90}")
    print("具体股票周期状态示例（不同市场阶段）")
    print("=" * 90)

    sample_code = code_list[0]
    close, dates = data[sample_code]
    for t in test_points[:5]:
        if t >= len(close):
            continue
        seg = close[t - WINDOW + 1: t + 1]
        state = vmd_cycle_state(seg, K=8, alpha=2000, tol=1e-5)
        ctx = format_cycle_context(state)
        date_str = str(dates[t])[:10]
        price = close[t]
        chg20 = (close[t] / close[t - 20] - 1) * 100 if t >= 20 else 0
        print(f"\n  {sample_code} @ {date_str} 价格={price:.2f} 近20日={chg20:+.1f}%")
        print(f"  {ctx}")


if __name__ == "__main__":
    main()
