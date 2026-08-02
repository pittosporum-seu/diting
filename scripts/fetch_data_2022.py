"""拉取 2022-09 ~ 2024-09 的日线数据，用于跨时段因子验证。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from diting.config import Config
Config()

SAMPLE_N = 300
DATA_DIR = Path("experiment/backtest_data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = DATA_DIR / "daily_2022_2024.csv"

START = "2022-09-01"
END = "2024-09-30"


def main():
    if CACHE_FILE.exists():
        print(f"缓存已存在: {CACHE_FILE}")
        df = pd.read_csv(CACHE_FILE)
        print(f"  {len(df)} 行, {df['code'].nunique()} 只股票, {df['date'].nunique()} 交易日")
        return

    stock_list = json.loads(
        (Path(__file__).parents[1] / "frontend/data/stock-list.json").read_text("utf-8")
    )
    valid_prefix = ("000", "001", "002", "003", "300", "301", "600", "601", "603", "605")
    codes = [s["code"] for s in stock_list
             if s.get("code") and s["code"][:3] in valid_prefix]
    step = max(1, len(codes) // SAMPLE_N)
    codes = codes[::step][:SAMPLE_N]
    print(f"样本: {len(codes)} 只, 区间: {START} ~ {END}")

    import akshare as ak

    all_dfs = []
    failed = 0
    for i, code in enumerate(codes):
        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{len(codes)} (成功{len(all_dfs)}/失败{failed})", flush=True)
        prefix = "sh" if code[0] == "6" else "sz"
        symbol = f"{prefix}{code}"
        try:
            df = ak.stock_zh_a_daily(symbol=symbol, adjust="qfq")
            if df is not None and len(df) > 100:
                df["date"] = pd.to_datetime(df["date"])
                df = df[(df["date"] >= START) & (df["date"] <= END)]
                if len(df) > 100:
                    df["code"] = code
                    all_dfs.append(df[["code", "date", "open", "close", "high", "low", "volume"]])
        except Exception:
            failed += 1
            continue
        if (i + 1) % 5 == 0:
            time.sleep(0.3)

    print(f"成功: {len(all_dfs)}, 失败: {failed}")
    if not all_dfs:
        print("错误：所有股票拉取失败")
        sys.exit(1)

    df_all = pd.concat(all_dfs, ignore_index=True)
    df_all.to_csv(CACHE_FILE, index=False)
    print(f"已缓存: {CACHE_FILE} ({len(df_all)} 行, {df_all['code'].nunique()} 只)")


if __name__ == "__main__":
    main()
