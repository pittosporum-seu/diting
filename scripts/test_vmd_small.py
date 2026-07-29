"""小批量 VMD 测试：验证多进程 + IC 计算正确性。"""
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")
from diting.config import Config

Config()

from ic_grid_full import _vmd_worker
from concurrent.futures import ProcessPoolExecutor


def main():
    # 加载数据，只取前 50 只
    df_all = pd.read_csv("experiment/backtest_data/daily_2022_2024.csv")
    data = {code: group.reset_index(drop=True) for code, group in df_all.groupby("code")}
    code_list, close_d = [], {}
    for code, df in list(data.items())[:50]:
        c = np.asarray(df["close"], dtype=float)
        if len(c) >= 400:
            code_list.append(code)
            close_d[code] = c
    n_days = min(len(close_d[c]) for c in code_list)
    print(f"测试: {len(code_list)} 只, {n_days} 天")

    # 小批量: K=3, alpha=2000, 10 个时间点
    K, alpha, window, tol = 3, 2000, 120, 1e-5
    test_times = list(range(window, min(window + 50, n_days - 20), 5))
    print(f"时间点: {len(test_times)} 个 (每5天)")

    t0 = time.time()
    all_tasks = []
    for t in test_times:
        for code in code_list:
            c = close_d[code]
            if t >= len(c):
                continue
            seg = c[max(0, t - window + 1): t + 1]
            if len(seg) >= K * 10:
                all_tasks.append((t, code, seg))

    print(f"任务数: {len(all_tasks)}")
    worker_args = [(seg, K, alpha, tol) for _, _, seg in all_tasks]

    with ProcessPoolExecutor(max_workers=16) as ex:
        results = list(ex.map(_vmd_worker, worker_args, chunksize=32))

    elapsed = time.time() - t0
    valid = sum(1 for r in results if r is not None)
    print(f"完成: {elapsed:.1f}s, 有效={valid}/{len(results)}")

    # 组装
    batch = {}
    for (t, code, _), factors in zip(all_tasks, results):
        if factors:
            batch.setdefault(t, {})[code] = factors

    # 算 vmd_period 的 IC_20d
    ics = []
    for t in test_times:
        if t not in batch:
            continue
        fvals, frets = [], []
        for code, f in batch[t].items():
            fv = f.get("period")
            if fv is None or not np.isfinite(fv):
                continue
            if t + 20 >= len(close_d[code]) or close_d[code][t] <= 0:
                continue
            fret = close_d[code][t + 20] / close_d[code][t] - 1
            fvals.append(fv)
            frets.append(fret)
        if len(fvals) >= 10:
            rho, _ = spearmanr(fvals, frets)
            if not np.isnan(rho):
                ics.append(rho)

    if ics:
        print(f"\nvmd_period K=3 a=2000 IC_20d:")
        print(f"  截面数={len(ics)}, IC均值={np.mean(ics):+.4f}, IR={np.mean(ics)/np.std(ics):.2f}")
        print(f"  各截面IC: {[f'{x:+.3f}' for x in ics]}")
    else:
        print("无有效IC")

    # 打印几个样本因子值
    print("\n样本因子值:")
    sample_t = test_times[0]
    for code in list(batch.get(sample_t, {}).keys())[:5]:
        f = batch[sample_t][code]
        print(f"  {code}: period={f.get('period'):.1f} cycle={f.get('cycle'):.3f} slope={f.get('slope'):.5f}")


if __name__ == "__main__":
    main()
