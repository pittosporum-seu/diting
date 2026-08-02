"""VMD 修正版：从 u[1:] 所有振荡模态提取周期因子。

- 窗口 = 250 交易日（≈1年）
- K = 8（更多分量）
- 每个 u[i] 都提取 period / power / phase
- 小批量 IC 验证
"""
from __future__ import annotations

import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, "src")
from diting.config import Config
Config()


def vmd_all_factors(close_seg: np.ndarray, K: int = 8, alpha: float = 2000.0,
                    tol: float = 1e-5) -> dict | None:
    """VMD 分解，从每个 u[i] 提取因子。"""
    from vmdpy import VMD

    N = len(close_seg)
    if N < K * 10:
        return None

    try:
        u, _, omega = VMD(close_seg, alpha, 0.0, K, 0, 1, tol)
    except Exception:
        return None

    factors = {}

    for i in range(min(K, len(u))):
        imf = u[i]
        if len(imf) < 8:
            continue

        # FFT 主周期
        fft_abs = np.abs(np.fft.rfft(imf - imf.mean()))
        freqs = np.fft.rfftfreq(len(imf), d=1.0)
        if len(fft_abs) <= 1:
            continue

        peak_idx = np.argmax(fft_abs[1:]) + 1
        peak_freq = freqs[peak_idx]
        period = float(1.0 / peak_freq) if peak_freq > 0 else float(N)

        total_power = np.sum(fft_abs[1:] ** 2)
        power_pct = float(fft_abs[peak_idx] ** 2 / total_power) if total_power > 0 else 0
        var = float(np.var(imf))

        factors[f"p{i}"] = period       # period
        factors[f"pw{i}"] = power_pct   # power concentration
        factors[f"v{i}"] = var          # variance

        # 相位（Hilbert）
        if period > 2:
            analytic = np.fft.ifft(np.fft.fft(imf) * 2)
            phase = np.angle(analytic)[-1]
            factors[f"ph{i}"] = float((phase / (2 * np.pi) + 0.5) % 1.0)

    # 趋势斜率（u[0]）
    if len(u[0]) >= 5:
        slope = np.polyfit(range(len(u[0])), u[0], 1)[0]
        avg = u[0].mean()
        factors["slope0"] = float(slope / avg) if avg > 0 else 0.0

    # VMD 中心频率（omega 最终值）
    if omega is not None and len(omega) > 0:
        for i in range(min(K, omega.shape[1])):
            cf = omega[-1, i] if len(omega.shape) > 1 else 0
            factors[f"cf{i}"] = float(1.0 / cf) if cf > 0 else float(N)

    return factors


def _worker(args):
    """多进程 worker。"""
    seg, K, alpha, tol = args
    return vmd_all_factors(seg, K=K, alpha=alpha, tol=tol)


def main():
    from concurrent.futures import ProcessPoolExecutor
    import os

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
    print(f"数据: {len(code_list)} 只, {n_days} 天, {workers} 进程\n")

    WINDOW = 250
    K = 8

    # ── Step 1: 单股诊断 ──
    print("=" * 70)
    print(f"Step 1: 单股诊断 (window={WINDOW}, K={K}, alpha=2000)")
    print("=" * 70)

    seg = close_d[code_list[0]][:WINDOW]
    t0 = time.time()
    f = vmd_all_factors(seg, K=K, alpha=2000, tol=1e-5)
    print(f"  耗时: {time.time()-t0:.2f}s\n")

    if f:
        print(f"  {'IMF':>5} {'周期(天)':>10} {'功率集中':>10} {'方差':>10} {'相位':>8} {'中心频率':>10}")
        print(f"  {'-'*60}")
        for i in range(K):
            p = f.get(f"p{i}", 0)
            pw = f.get(f"pw{i}", 0)
            v = f.get(f"v{i}", 0)
            ph = f.get(f"ph{i}", -1)
            cf = f.get(f"cf{i}", 0)
            ph_s = f"{ph:.3f}" if ph >= 0 else "  -  "
            label = "趋势" if i == 0 else f"振荡{i}"
            print(f"  u[{i}] {label:>4} {p:>8.1f}  {pw:>8.3f}  {v:>10.5f}  {ph_s:>8}  {cf:>8.1f}")

    # ── Step 2: 区分度（多只股票同一时间点）──
    print(f"\n{'='*70}")
    print(f"Step 2: 区分度 (t={WINDOW}, 前10只股票)")
    print("=" * 70)

    t = WINDOW
    print(f"\n  {'code':>6} | {'u1周期':>7} {'u2周期':>7} {'u3周期':>7} {'u4周期':>7} | {'dom':>4} {'slope':>8}")
    print(f"  {'-'*65}")
    for code in code_list[:10]:
        c = close_d[code]
        if t >= len(c):
            continue
        seg = c[t - WINDOW + 1: t + 1]
        f = vmd_all_factors(seg, K=K, alpha=2000, tol=1e-5)
        if f:
            p1 = f.get("p1", 0)
            p2 = f.get("p2", 0)
            p3 = f.get("p3", 0)
            p4 = f.get("p4", 0)
            sl = f.get("slope0", 0)
            # 找 u[1:] 中方差最大的
            vars_list = [(i, f.get(f"v{i}", 0)) for i in range(1, K)]
            dom_i = max(vars_list, key=lambda x: x[1])[0]
            print(f"  {code:>6} | {p1:>7.1f} {p2:>7.1f} {p3:>7.1f} {p4:>7.1f} | u[{dom_i}] {sl:>+8.5f}")

    # ── Step 3: 全量 IC（日粒度 + 多进程）──
    print(f"\n{'='*70}")
    print(f"Step 3: 全量 IC ({len(code_list)}只, 日粒度, 多进程)")
    print("=" * 70)

    test_times = list(range(WINDOW, n_days - 20, 1))  # 日粒度
    print(f"  截面数: {len(test_times)}, 每截面 {len(code_list)} 只")

    # 收集所有任务
    all_tasks = []  # (t, code, seg)
    for t in test_times:
        for code in code_list:
            c = close_d[code]
            if t >= len(c):
                continue
            seg = c[t - WINDOW + 1: t + 1]
            if len(seg) >= K * 10:
                all_tasks.append((t, code, seg))

    print(f"  总任务: {len(all_tasks)} 条, 开始多进程计算...", flush=True)
    t0 = time.time()

    worker_args = [(seg, K, 2000, 1e-5) for _, _, seg in all_tasks]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(_worker, worker_args, chunksize=64))

    elapsed = time.time() - t0
    valid = sum(1 for r in results if r is not None)
    print(f"  完成: {elapsed:.1f}s, 有效={valid}/{len(results)}", flush=True)

    # 组装
    all_f = {}
    for (t, code, _), fac in zip(all_tasks, results):
        if fac:
            all_f.setdefault(t, {})[code] = fac

    # 测试所有因子
    factor_names = []
    for i in range(K):
        factor_names.extend([f"p{i}", f"pw{i}", f"ph{i}"])
    factor_names.append("slope0")

    print(f"  {'因子':<12} {'IC_5d':>8} {'IC_10d':>8} {'IC_20d':>8} {'IR_20d':>8} {'n':>4}")
    print(f"  {'-'*56}")

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
                if len(fvals) >= 10:
                    rho, _ = spearmanr(fvals, frets)
                    if not np.isnan(rho):
                        ics_list.append(rho)

        if ics_20:
            m5 = np.mean(ics_5) if ics_5 else 0
            m10 = np.mean(ics_10) if ics_10 else 0
            m20 = np.mean(ics_20)
            ir = m20 / np.std(ics_20) if np.std(ics_20) > 0 else 0
            flag = " ***" if abs(m20) > 0.05 else ""
            print(f"  {fname:<12} {m5:>+8.4f} {m10:>+8.4f} {m20:>+8.4f} {ir:>+8.2f} {len(ics_20):>4}{flag}")
        else:
            print(f"  {fname:<12} {'N/A':>8} {'N/A':>8} {'N/A':>8} {'N/A':>8}    0")


if __name__ == "__main__":
    main()
