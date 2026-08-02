"""VMD 斜率因子：每个 IMF 当前位置的斜率（多时间框架动量）。"""
from __future__ import annotations

import sys
import time
import os

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from concurrent.futures import ProcessPoolExecutor

sys.path.insert(0, "src")
from diting.config import Config
Config()


def vmd_slope_factors(close_seg: np.ndarray, K: int = 8, alpha: float = 2000.0,
                      tol: float = 1e-5, lookback: int = 5) -> dict | None:
    """VMD 分解 + 每个 IMF 的当前斜率。

    斜率 = 最近 lookback 个点的线性回归斜率，归一化（/均价）。
    """
    from vmdpy import VMD

    N = len(close_seg)
    if N < K * 10:
        return None

    try:
        u, _, _ = VMD(close_seg, alpha, 0.0, K, 0, 1, tol)
    except Exception:
        return None

    factors = {}
    price_scale = close_seg.mean()  # 用均价归一化

    for i in range(min(K, len(u))):
        imf = u[i]
        if len(imf) < lookback + 1:
            continue

        # 最近 lookback 个点的斜率
        recent = imf[-lookback:]
        slope = np.polyfit(range(lookback), recent, 1)[0]
        factors[f"s{i}"] = float(slope / price_scale) if price_scale > 0 else 0.0

        # 也看稍长一点的斜率（10天）
        if len(imf) >= 10:
            recent10 = imf[-10:]
            slope10 = np.polyfit(range(10), recent10, 1)[0]
            factors[f"s{i}_10"] = float(slope10 / price_scale) if price_scale > 0 else 0.0

        # 方向（sign）
        factors[f"d{i}"] = float(np.sign(slope))

    # 复合：多周期共振（u[1]+u[2]+u[3] 斜率同向得分）
    if all(f"s{i}" in factors for i in range(1, 4)):
        s1, s2, s3 = factors["s1"], factors["s2"], factors["s3"]
        # 共振分：三个都为正=+3，两正一负=+1，etc
        factors["resonance"] = float(np.sign(s1) + np.sign(s2) + np.sign(s3))
        # 加权和（长周期权重更大）
        factors["weighted_slope"] = 0.5 * s1 + 0.3 * s2 + 0.2 * s3

    return factors


def _worker(args):
    seg, K, alpha, tol, lookback = args
    return vmd_slope_factors(seg, K=K, alpha=alpha, tol=tol, lookback=lookback)


def main():
    df_all = pd.read_csv("experiment/backtest_data/daily_2022_2024.csv")
    data = {code: group.reset_index(drop=True) for code, group in df_all.groupby("code")}
    code_list, close_d = [], {}
    for code, df in data.items():
        c = np.asarray(df["close"], dtype=float)
        if len(c) >= 400:
            code_list.append(code)
            close_d[code] = c
    n_days = min(len(close_d[c]) for c in code_list)
    workers = min(os.cpu_count() or 4, 16)
    print(f"数据: {len(code_list)} 只, {n_days} 天, {workers} 进程")

    WINDOW = 250
    K = 8
    LOOKBACK = 5

    # 全量日粒度
    test_times = list(range(WINDOW, n_days - 20, 1))
    print(f"截面: {len(test_times)}, 每截面 {len(code_list)} 只")

    # 收集任务
    all_tasks = []
    for t in test_times:
        for code in code_list:
            c = close_d[code]
            if t >= len(c):
                continue
            seg = c[t - WINDOW + 1: t + 1]
            if len(seg) >= K * 10:
                all_tasks.append((t, code, seg))

    print(f"总任务: {len(all_tasks)}, 开始...", flush=True)
    t0 = time.time()

    worker_args = [(seg, K, 2000, 1e-5, LOOKBACK) for _, _, seg in all_tasks]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_worker, worker_args, chunksize=64))

    elapsed = time.time() - t0
    valid = sum(1 for r in results if r is not None)
    print(f"完成: {elapsed:.1f}s, 有效={valid}/{len(results)}", flush=True)

    # 组装
    all_f = {}
    for (t, code, _), fac in zip(all_tasks, results):
        if fac:
            all_f.setdefault(t, {})[code] = fac

    # IC 计算
    factor_names = []
    for i in range(K):
        factor_names.extend([f"s{i}", f"s{i}_10", f"d{i}"])
    factor_names.extend(["resonance", "weighted_slope"])

    print(f"\n{'因子':<16} {'IC_5d':>8} {'IC_10d':>8} {'IC_20d':>8} {'IR_20d':>8} {'n':>4}")
    print("-" * 60)

    for fname in factor_names:
        ics_5, ics_10, ics_20 = [], [], []
        for t in test_times:
            if t not in all_f:
                continue
            for fwd, ics_list in [(5, ics_5), (10, ics_10), (20, ics_20)]:
                fvals, frets = [], []
                for code, fac in all_f[t].items():
                    fv = fac.get(fname)
                    if fv is None or not np.isfinite(fv):
                        continue
                    if t + fwd >= len(close_d[code]) or close_d[code][t] <= 0:
                        continue
                    fret = close_d[code][t + fwd] / close_d[code][t] - 1
                    fvals.append(fv)
                    frets.append(fret)
                if len(fvals) >= 30:
                    rho, _ = spearmanr(fvals, frets)
                    if not np.isnan(rho):
                        ics_list.append(rho)

        if ics_20:
            m5 = np.mean(ics_5) if ics_5 else 0
            m10 = np.mean(ics_10) if ics_10 else 0
            m20 = np.mean(ics_20)
            ir = m20 / np.std(ics_20) if np.std(ics_20) > 0 else 0
            flag = " ***" if abs(m20) > 0.05 else ""
            print(f"  {fname:<14} {m5:>+8.4f} {m10:>+8.4f} {m20:>+8.4f} {ir:>+8.2f} {len(ics_20):>4}{flag}")
        else:
            print(f"  {fname:<14} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>8}    0")


if __name__ == "__main__":
    main()
