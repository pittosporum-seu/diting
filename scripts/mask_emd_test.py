"""频率诊断 + Mask EMD 因子原型。

步骤：
1. FFT 诊断：看 120 天价格序列的频率结构
2. 设计 8 个 mask 频率（基于最低频）
3. Mask EMD 分解 → 提取周期因子
4. 小批量 IC 测试
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


# ── 1. FFT 频率诊断 ──────────────────────────────────────

def fft_diagnose(close: np.ndarray, window: int = 120):
    """对最后 window 天做 FFT，返回频率和功率谱。"""
    seg = close[-window:]
    # 去趋势（减线性拟合）
    x = np.arange(len(seg))
    trend = np.polyfit(x, seg, 1)
    detrended = seg - np.polyval(trend, x)

    fft_vals = np.fft.rfft(detrended)
    power = np.abs(fft_vals) ** 2
    freqs = np.fft.rfftfreq(len(detrended), d=1.0)  # 单位: cycles/day

    # 排除 DC (freq=0)
    power_no_dc = power[1:]
    freqs_no_dc = freqs[1:]

    # Top 5 频率
    top_idx = np.argsort(power_no_dc)[::-1][:5]
    print("  FFT Top 5 频率分量:")
    print(f"  {'排名':>4} {'频率(c/d)':>10} {'周期(天)':>10} {'功率占比':>10}")
    total_power = power_no_dc.sum()
    for rank, idx in enumerate(top_idx, 1):
        f = freqs_no_dc[idx]
        period = 1.0 / f if f > 0 else float("inf")
        pct = power_no_dc[idx] / total_power * 100
        print(f"  {rank:>4} {f:>10.4f} {period:>10.1f} {pct:>9.1f}%")

    # 最低频（第一个峰）
    lowest_freq = freqs_no_dc[0]  # = 1/window
    print(f"\n  最低可分辨频率: {lowest_freq:.4f} c/d = {1/lowest_freq:.0f} 天周期")
    print(f"  频率分辨率: {lowest_freq:.4f} c/d")

    return freqs_no_dc, power_no_dc


# ── 2. Mask EMD ──────────────────────────────────────────

def mask_emd_decompose(signal: np.ndarray, n_masks: int = 8,
                       base_period: float | None = None) -> list[np.ndarray]:
    """Mask EMD：用 n_masks 个掩膜信号辅助 EMD 分解。

    Args:
        signal: 输入信号（去趋势后的价格）
        n_masks: 掩膜数量
        base_period: 最低频掩膜的周期（天）。None=自动（用信号长度）

    Returns:
        IMFs 列表（从低频到高频）
    """
    from PyEMD import EMD

    N = len(signal)
    if base_period is None:
        base_period = N  # 最低频 = 信号全长

    # 设计 8 个 mask 频率：从 base_period 开始，按倍频递减
    # mask_periods = [base, base/2, base/4, ..., base/2^(n-1)]
    mask_periods = [base_period / (2 ** i) for i in range(n_masks)]
    mask_freqs = [1.0 / p for p in mask_periods]

    t = np.arange(N)

    # 对每个 mask，做 ±mask 的 EMD，取平均
    all_imfs = []
    emd = EMD()
    emd.FIXE = 10  # 固定迭代次数（加速）
    emd.MAX_ITERATION = 50

    for mf in mask_freqs:
        mask_signal = np.sin(2 * np.pi * mf * t)
        amplitude = np.std(signal) * 0.5  # mask 幅度 = 信号标准差的 50%

        try:
            # +mask
            imfs_plus = emd.emd(signal + amplitude * mask_signal, max_imf=5)
            # -mask
            imfs_minus = emd.emd(signal - amplitude * mask_signal, max_imf=5)

            # 取平均（抵消 mask 的影响）
            n_imf = min(len(imfs_plus), len(imfs_minus))
            avg_imfs = (imfs_plus[:n_imf] + imfs_minus[:n_imf]) / 2
            all_imfs.append(avg_imfs)
        except Exception:
            continue

    if not all_imfs:
        return []

    # 对所有 mask 的结果取集成平均
    # 找最常见的 IMF 数量
    n_imfs = [len(imfs) for imfs in all_imfs]
    target_n = max(set(n_imfs), key=n_imfs.count)

    # 只保留 target_n 个 IMF 的结果
    valid = [imfs for imfs in all_imfs if len(imfs) >= target_n]
    if not valid:
        return []

    ensemble = np.mean([imfs[:target_n] for imfs in valid], axis=0)
    return [ensemble[i] for i in range(target_n)]


def extract_cycle_factors(signal: np.ndarray, imfs: list[np.ndarray]) -> dict:
    """从 Mask EMD 的 IMF 中提取周期因子。"""
    factors = {}
    N = len(signal)

    if not imfs or len(imfs) < 2:
        return factors

    # IMF[0] 通常是最高频，IMF[-1] 是最低频（趋势）
    # 找"中周期" IMF：功率最大的非趋势分量
    powers = [np.var(imf) for imf in imfs]

    # 排除最后一个（趋势）和第一个（噪声），找中间功率最大的
    if len(imfs) >= 3:
        candidate_range = range(0, len(imfs) - 1)  # 排除最后一个（趋势）
    else:
        candidate_range = range(len(imfs))

    best_idx = max(candidate_range, key=lambda i: powers[i])
    cycle_imf = imfs[best_idx]

    # 对 cycle_imf 做 FFT 找主周期
    fft_vals = np.abs(np.fft.rfft(cycle_imf))
    freqs = np.fft.rfftfreq(len(cycle_imf), d=1.0)
    # 排除 DC
    if len(fft_vals) > 1:
        peak_idx = np.argmax(fft_vals[1:]) + 1
        peak_freq = freqs[peak_idx]
        factors["cycle_period"] = float(1.0 / peak_freq) if peak_freq > 0 else float(N)
        factors["cycle_power_pct"] = float(fft_vals[peak_idx] ** 2 / np.sum(fft_vals[1:] ** 2))
    else:
        factors["cycle_period"] = float(N)
        factors["cycle_power_pct"] = 0.0

    # 周期相位：当前处于周期的什么位置（0=谷底, 0.5=零轴, 1=峰顶）
    if factors["cycle_period"] > 2:
        # 用最近一个完整周期的数据算相位
        period_len = int(factors["cycle_period"])
        recent = cycle_imf[-period_len:] if len(cycle_imf) >= period_len else cycle_imf
        if len(recent) > 2:
            # Hilbert 相位
            analytic = np.fft.ifft(np.fft.fft(recent) * 2)
            phase = np.angle(analytic)[-1]
            factors["cycle_phase"] = float((phase / (2 * np.pi) + 0.5) % 1.0)

    # 趋势方向：最后一个 IMF（最慢）的斜率
    trend_imf = imfs[-1]
    if len(trend_imf) >= 5:
        slope = np.polyfit(range(len(trend_imf)), trend_imf, 1)[0]
        avg = np.abs(trend_imf.mean())
        factors["trend_slope"] = float(slope / avg) if avg > 0 else 0.0

    # 趋势背离：近期方向 vs 整体方向
    if len(trend_imf) >= 10:
        recent_dir = np.sign(trend_imf[-1] - trend_imf[-5])
        overall_dir = np.sign(np.polyfit(range(len(trend_imf)), trend_imf, 1)[0])
        factors["trend_broken"] = float(recent_dir != overall_dir)

    factors["n_imfs"] = len(imfs)
    factors["best_imf_idx"] = best_idx

    return factors


# ── 3. 主程序 ──────────────────────────────────────────

def main():
    # 加载数据
    df_all = pd.read_csv("experiment/backtest_data/daily_2022_2024.csv")
    data = {code: group.reset_index(drop=True) for code, group in df_all.groupby("code")}
    code_list, close_d = [], {}
    for code, df in list(data.items())[:50]:
        c = np.asarray(df["close"], dtype=float)
        if len(c) >= 400:
            code_list.append(code)
            close_d[code] = c
    n_days = min(len(close_d[c]) for c in code_list)
    print(f"数据: {len(code_list)} 只, {n_days} 天\n")

    # ── Step 1: FFT 诊断（看几只股票的频率结构）──
    print("=" * 70)
    print("Step 1: FFT 频率诊断")
    print("=" * 70)
    for code in code_list[:3]:
        print(f"\n  股票 {code}:")
        fft_diagnose(close_d[code], window=120)

    # ── Step 2: Mask EMD 测试（单只股票）──
    print(f"\n{'=' * 70}")
    print("Step 2: Mask EMD 分解测试")
    print("=" * 70)

    test_code = code_list[0]
    seg = close_d[test_code][-120:]
    # 去趋势
    x = np.arange(len(seg))
    trend = np.polyfit(x, seg, 1)
    detrended = seg - np.polyval(trend, x)

    print(f"\n  股票 {test_code}, 120天窗口")
    t0 = time.time()
    imfs = mask_emd_decompose(detrended, n_masks=8, base_period=120)
    elapsed = time.time() - t0
    print(f"  Mask EMD: {len(imfs)} 个 IMF, 耗时 {elapsed:.2f}s")

    for i, imf in enumerate(imfs):
        # 每个 IMF 的主频
        fft_vals = np.abs(np.fft.rfft(imf))
        freqs = np.fft.rfftfreq(len(imf), d=1.0)
        if len(fft_vals) > 1:
            peak_idx = np.argmax(fft_vals[1:]) + 1
            peak_period = 1.0 / freqs[peak_idx] if freqs[peak_idx] > 0 else float("inf")
        else:
            peak_period = float("inf")
        print(f"    IMF[{i}]: var={np.var(imf):.4f}, 主周期={peak_period:.1f}天")

    factors = extract_cycle_factors(detrended, imfs)
    print(f"\n  提取因子: {factors}")

    # ── Step 3: 小批量 IC 测试 ──
    print(f"\n{'=' * 70}")
    print("Step 3: 小批量 IC 测试 (Mask EMD cycle_period)")
    print("=" * 70)

    window = 120
    test_times = list(range(window, min(window + 100, n_days - 20), 10))  # 10 个点
    print(f"  时间点: {len(test_times)} 个, 股票: {len(code_list)} 只")

    t0 = time.time()
    all_factors = {}  # {t: {code: factors}}

    for t in test_times:
        all_factors[t] = {}
        for code in code_list:
            c = close_d[code]
            if t >= len(c):
                continue
            seg = c[t - window + 1: t + 1]
            # 去趋势
            x = np.arange(len(seg))
            tr = np.polyfit(x, seg, 1)
            det = seg - np.polyval(tr, x)

            imfs = mask_emd_decompose(det, n_masks=8, base_period=window)
            if imfs:
                f = extract_cycle_factors(det, imfs)
                if f:
                    all_factors[t][code] = f

    elapsed = time.time() - t0
    n_tasks = sum(len(v) for v in all_factors.values())
    print(f"  完成: {elapsed:.1f}s, {n_tasks} 条有效结果")

    # 算 IC
    for factor_name in ["cycle_period", "cycle_phase", "trend_slope", "trend_broken"]:
        ics = []
        for t in test_times:
            if t not in all_factors:
                continue
            fvals, frets = [], []
            for code, f in all_factors[t].items():
                fv = f.get(factor_name)
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
            ic_mean = np.mean(ics)
            ic_std = np.std(ics)
            ir = ic_mean / ic_std if ic_std > 0 else 0
            print(f"  {factor_name:<16} IC_20d={ic_mean:+.4f}  IR={ir:+.2f}  (n={len(ics)})")
        else:
            print(f"  {factor_name:<16} 无有效IC")


if __name__ == "__main__":
    main()
