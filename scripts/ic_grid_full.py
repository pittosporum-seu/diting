"""全因子 × 全参数 网格搜索 — 大胆扩展版。

覆盖 6 大类因子：
  1. 趋势/位置: dist_high, price_vs_ma, ret, ma_align
  2. 超买超卖: rsi, boll_pos, kdj_k
  3. 波动/风险: volatility, atr, downside_vol
  4. 量价: vol_ratio, obv_slope, support_distance
  5. VMD 周期: cycle_position, trend_slope, dominant_period, trend_broken
  6. 复合: risk_adj_momentum, volume_price_diverge, mean_reversion_zscore

IC = 因子截面排名 vs 未来收益的 Spearman 相关
IC_IR = IC均值 / IC标准差（稳定性）

用法:
  uv run python scripts/ic_grid_full.py              # 全量（含VMD，慢）
  uv run python scripts/ic_grid_full.py --no-vmd     # 跳过VMD（快）
  uv run python scripts/ic_grid_full.py --vmd-only   # 只跑VMD
"""
from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# ── 加载数据（由 main() 中根据 --data 参数设置）──────────────
DATA_FILE = Path("experiment/backtest_data/daily_2y.csv")
def load_data(data_file: Path, min_days: int = 120):
    """加载数据并填充全局变量。"""
    global code_list, close_d, high_d, low_d, vol_d, n_days
    if not data_file.exists():
        print(f"错误：数据文件不存在: {data_file}")
        sys.exit(1)
    print(f"加载数据: {data_file}")
    df_all = pd.read_csv(data_file)
    data = {code: group.reset_index(drop=True) for code, group in df_all.groupby("code")}
    print(f"原始: {len(data)} 只股票")

    code_list = []
    close_d, high_d, low_d, vol_d = {}, {}, {}, {}
    for code, df in data.items():
        c = np.asarray(df["close"], dtype=float)
        if len(c) < min_days:
            continue
        code_list.append(code)
        close_d[code] = c
        high_d[code] = np.asarray(df["high"], dtype=float)
        low_d[code] = np.asarray(df["low"], dtype=float)
        vol_d[code] = np.asarray(df["volume"], dtype=float) if "volume" in df.columns else np.ones_like(c)

    n_days = min(len(close_d[c]) for c in code_list)
    print(f"有效: {len(code_list)} 只, {n_days} 交易日 (min_days={min_days})\n")

# ── IC 计算引擎 ──────────────────────────────────────
REBALANCE = 5
FORWARD_PERIODS = [5, 10, 20]


def compute_ic_series(factor_fn, forward_period: int, min_t: int = 60) -> list[float]:
    """通用 IC 序列计算。factor_fn(code, t) -> float|None"""
    ics = []
    for t in range(min_t, n_days - forward_period, REBALANCE):
        fvals, frets = [], []
        for code in code_list:
            if t >= len(close_d[code]) or t + forward_period >= len(close_d[code]):
                continue
            fv = factor_fn(code, t)
            if fv is None or not np.isfinite(fv):
                continue
            if close_d[code][t] <= 0:
                continue
            fut_ret = close_d[code][t + forward_period] / close_d[code][t] - 1
            fvals.append(fv)
            frets.append(fut_ret)
        if len(fvals) < 30:
            continue
        rho, _ = spearmanr(fvals, frets)
        if not np.isnan(rho):
            ics.append(rho)
    return ics


def ic_stats(ics: list[float]) -> dict:
    if not ics:
        return {"ic": None, "ir": None, "n": 0}
    m, s = np.mean(ics), np.std(ics)
    return {"ic": round(float(m), 5), "ir": round(float(m / s), 3) if s > 0 else 0, "n": len(ics)}


# ── 快速因子计算函数 ──────────────────────────────────

def make_dist_high(n: int):
    def fn(code, t):
        if t < n:
            return None
        hN = high_d[code][t - n + 1: t + 1].max()
        return close_d[code][t] / hN if hN > 0 else None
    return fn


def make_price_vs_ma(n: int):
    def fn(code, t):
        if t < n:
            return None
        ma = close_d[code][t - n + 1: t + 1].mean()
        return (close_d[code][t] - ma) / ma if ma > 0 else None
    return fn


def make_ret(n: int):
    def fn(code, t):
        if t < n or close_d[code][t - n] <= 0:
            return None
        return close_d[code][t] / close_d[code][t - n] - 1
    return fn


def make_rsi(n: int):
    def fn(code, t):
        if t < n + 1:
            return None
        delta = np.diff(close_d[code][t - n: t + 1])
        gain = np.where(delta > 0, delta, 0).mean()
        loss = np.where(delta < 0, -delta, 0).mean()
        return 100 - 100 / (1 + gain / loss) if loss > 0 else 100.0
    return fn


def make_boll_pos(n: int):
    def fn(code, t):
        if t < n:
            return None
        seg = close_d[code][t - n + 1: t + 1]
        ma, std = seg.mean(), seg.std()
        upper, lower = ma + 2 * std, ma - 2 * std
        return (close_d[code][t] - lower) / (upper - lower) if upper > lower else 0.5
    return fn


def make_kdj_k(n: int):
    def fn(code, t):
        if t < n:
            return None
        hN = high_d[code][t - n + 1: t + 1].max()
        lN = low_d[code][t - n + 1: t + 1].min()
        if hN == lN:
            return 50.0
        rsv = (close_d[code][t] - lN) / (hN - lN) * 100
        # 简化: 用最近 n 日 RSV 的 EMA 近似 K
        return float(rsv)
    return fn


def make_volatility(n: int):
    def fn(code, t):
        if t < n + 1:
            return None
        seg = close_d[code][t - n: t + 1]
        rets = np.diff(seg) / seg[:-1]
        return float(np.std(rets))
    return fn


def make_atr(n: int):
    def fn(code, t):
        if t < n + 1:
            return None
        h, l, c = high_d[code], low_d[code], close_d[code]
        trs = []
        for i in range(t - n + 1, t + 1):
            tr = max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1]))
            trs.append(tr)
        atr_val = np.mean(trs)
        return atr_val / c[t] if c[t] > 0 else None  # 归一化
    return fn


def make_downside_vol(n: int):
    def fn(code, t):
        if t < n + 1:
            return None
        seg = close_d[code][t - n: t + 1]
        rets = np.diff(seg) / seg[:-1]
        neg = rets[rets < 0]
        return float(np.std(neg)) if len(neg) >= 3 else None
    return fn


def make_vol_ratio(s: int, l: int):
    def fn(code, t):
        if t < l:
            return None
        v = vol_d[code]
        vs = v[t - s + 1: t + 1].mean()
        vl = v[t - l + 1: t + 1].mean()
        return vs / vl if vl > 0 else None
    return fn


def make_obv_slope(n: int):
    def fn(code, t):
        if t < n + 1:
            return None
        c, v = close_d[code], vol_d[code]
        direction = np.sign(np.diff(c[t - n: t + 1]))
        obv = np.cumsum(direction * v[t - n + 1: t + 1])
        # 线性回归斜率（归一化）
        x = np.arange(len(obv))
        slope = np.polyfit(x, obv, 1)[0]
        avg_vol = v[t - n: t + 1].mean()
        return slope / avg_vol if avg_vol > 0 else None
    return fn


def make_support_distance(n: int):
    def fn(code, t):
        if t < n:
            return None
        hN = high_d[code][t - n + 1: t + 1].max()
        lN = low_d[code][t - n + 1: t + 1].min()
        if hN == lN:
            return 0.5
        return (close_d[code][t] - lN) / (hN - lN)
    return fn


def make_ma_align(_unused: int = 0):
    def fn(code, t):
        if t < 60:
            return None
        c = close_d[code]
        ma5 = c[t - 4:t + 1].mean()
        ma10 = c[t - 9:t + 1].mean()
        ma20 = c[t - 19:t + 1].mean()
        ma60 = c[t - 59:t + 1].mean()
        return float((ma5 > ma10) + (ma10 > ma20) + (ma20 > ma60))
    return fn


# ── 复合因子 ──────────────────────────────────────────

def make_risk_adj_momentum(ret_n: int, vol_n: int):
    def fn(code, t):
        if t < max(ret_n, vol_n) + 1:
            return None
        c = close_d[code]
        if c[t - ret_n] <= 0:
            return None
        ret = c[t] / c[t - ret_n] - 1
        seg = c[t - vol_n: t + 1]
        rets = np.diff(seg) / seg[:-1]
        vol = np.std(rets)
        return ret / vol if vol > 0 else None
    return fn


def make_volume_price_diverge(window: int):
    def fn(code, t):
        if t < window + 1:
            return None
        c, v = close_d[code], vol_d[code]
        price_chg = c[t] / c[t - window] - 1
        vol_chg = v[t - window + 1: t + 1].mean() / v[t - 2 * window + 1: t - window + 1].mean() - 1 \
            if t >= 2 * window else None
        if vol_chg is None:
            return None
        # 量价背离: 价涨量缩 或 价跌量增 → 正值表示背离程度
        return -price_chg * vol_chg
    return fn


def make_mean_reversion_zscore(n: int):
    def fn(code, t):
        if t < n:
            return None
        seg = close_d[code][t - n + 1: t + 1]
        ma, std = seg.mean(), seg.std()
        return (close_d[code][t] - ma) / std if std > 0 else None
    return fn


# ── VMD 因子 ──────────────────────────────────────────

def _vmd_worker(args):
    """单条 VMD 分解 worker（用于多进程）。用原版 vmdpy 保证正确性。"""
    seg, k, alpha, tol = args
    try:
        from vmdpy import VMD
        u, _, _ = VMD(seg, alpha, 0.0, k, 0, 1, tol)
        trend = u[0]
        factors = {}

        if len(trend) >= 4:
            phase = np.angle(np.fft.fft(trend))[1]
            factors["cycle"] = float((np.sin(phase) + 1) / 2)

        if len(trend) >= 5:
            slope = np.polyfit(range(len(trend)), trend, 1)[0]
            avg = trend.mean()
            factors["slope"] = slope / avg if avg > 0 else None

        if len(trend) >= 8:
            fft_abs = np.abs(np.fft.fft(trend - trend.mean()))
            freqs = np.fft.fftfreq(len(trend))
            pos = freqs > 0
            if pos.any():
                idx = np.argmax(fft_abs[pos])
                freq = freqs[pos][idx]
                factors["period"] = float(1 / freq) if freq > 0 else float(len(trend))

        if len(trend) >= 10:
            recent_dir = np.sign(trend[-1] - trend[-5])
            overall_dir = np.sign(np.polyfit(range(len(trend)), trend, 1)[0])
            factors["broken"] = float(recent_dir != overall_dir)

        return factors
    except Exception:
        return None


def vmd_decompose_batch(k: int, alpha: int, window: int = 120,
                        rebalance: int = 1, tol: float = 1e-5,
                        workers: int = 0) -> dict[int, dict[str, dict]]:
    """批量 VMD 分解，多进程并行。

    每组 (K,α) 只创建一次进程池，所有 (code, t) 对批量处理。
    返回 {t: {code: {factor: value}}}。
    """
    from concurrent.futures import ProcessPoolExecutor
    import os

    if workers <= 0:
        workers = min(os.cpu_count() or 4, 16)

    time_points = list(range(window, n_days - 20, rebalance))

    # 收集所有任务: (task_idx, code, seg)
    all_tasks = []  # (t_idx, code, seg)
    for t in time_points:
        for code in code_list:
            c = close_d[code]
            if t >= len(c):
                continue
            start = max(0, t - window + 1)
            seg = c[start: t + 1]
            if len(seg) < k * 10:
                continue
            all_tasks.append((t, code, seg))

    if not all_tasks:
        return {t: {} for t in time_points}

    # 一次性多进程执行
    worker_args = [(seg, k, alpha, tol) for _, _, seg in all_tasks]
    print(f"    VMD: {len(all_tasks)} 条任务, {workers} 进程, tol={tol}", flush=True)

    with ProcessPoolExecutor(max_workers=workers) as executor:
        factor_list = list(executor.map(_vmd_worker, worker_args, chunksize=64))

    # 组装结果
    results: dict[int, dict[str, dict]] = {t: {} for t in time_points}
    for (t, code, _), factors in zip(all_tasks, factor_list):
        if factors:
            results[t][code] = factors

    return results


# ── 参数搜索空间（大胆扩展）──────────────────────────────

FAST_FACTORS: dict[str, list] = {
    # 趋势/位置
    "dist_high": [3, 5, 7, 10, 15, 20, 30, 40, 60, 90, 120],
    "price_vs_ma": [3, 5, 7, 10, 15, 20, 30, 40, 60, 90, 120],
    "ret": [2, 3, 5, 7, 10, 15, 20, 30, 40, 60, 90, 120],
    "ma_align": [0],
    # 超买超卖
    "rsi": [3, 5, 7, 10, 14, 21, 28, 35, 42, 56],
    "boll_pos": [5, 10, 15, 20, 25, 30, 40, 60],
    "kdj_k": [5, 9, 14, 21, 28, 35],
    # 波动/风险
    "volatility": [5, 10, 15, 20, 30, 40, 60, 90],
    "atr": [7, 10, 14, 20, 30, 40, 60],
    "downside_vol": [10, 20, 30, 40, 60, 90],
    # 量价
    "support_distance": [10, 20, 30, 40, 60, 90],
    "obv_slope": [5, 10, 15, 20, 30, 60],
}

# vol_ratio 是双参数: (short, long)
VOL_RATIO_GRID = [(s, s * m) for s in [2, 3, 5, 7, 10, 15, 20] for m in [2, 3, 4, 5]]

# 复合因子
COMPOSITE_GRID = {
    "risk_adj_mom": [(rn, vn) for rn in [5, 10, 20, 40, 60] for vn in [10, 15, 20, 30]],
    "vol_price_diverge": [3, 5, 7, 10, 15, 20],
    "mean_reversion_z": [10, 20, 30, 40, 60, 90, 120],
}

# VMD 网格
VMD_K_GRID = [3, 4, 5, 6, 8]
VMD_ALPHA_GRID = [100, 200, 500, 1000, 2000, 5000]
VMD_WINDOW = 120  # 固定输入窗口
VMD_REBALANCE = 1  # 日粒度
VMD_TOL = 1e-5  # 收敛精度（放宽以加速）
VMD_WORKERS = 0  # 0=自动(CPU核数)

# 因子工厂映射
FACTOR_FACTORY = {
    "dist_high": lambda p: make_dist_high(p),
    "price_vs_ma": lambda p: make_price_vs_ma(p),
    "ret": lambda p: make_ret(p),
    "rsi": lambda p: make_rsi(p),
    "boll_pos": lambda p: make_boll_pos(p),
    "kdj_k": lambda p: make_kdj_k(p),
    "volatility": lambda p: make_volatility(p),
    "atr": lambda p: make_atr(p),
    "downside_vol": lambda p: make_downside_vol(p),
    "support_distance": lambda p: make_support_distance(p),
    "obv_slope": lambda p: make_obv_slope(p),
    "ma_align": lambda p: make_ma_align(p),
}


# ── 主程序 ──────────────────────────────────────────

def run_fast_factors() -> list[dict]:
    """跑所有快速因子的 IC 网格搜索。"""
    results = []
    total = sum(len(v) for v in FAST_FACTORS.values()) + len(VOL_RATIO_GRID) + \
        sum(len(v) for v in COMPOSITE_GRID.values())
    done = 0
    t0 = time.time()

    print(f"{'='*100}")
    print(f"快速因子 IC 网格搜索（{len(code_list)} 只股票, 每{REBALANCE}日调仓）")
    print(f"{'='*100}")
    header = f"{'因子':<22} {'参数':>10} | {'IC_5d':>8} {'IR_5d':>6} | {'IC_10d':>8} {'IR_10d':>6} | {'IC_20d':>8} {'IR_20d':>6}"
    print(header)
    print("-" * 100)

    # 单参数因子
    for fname, params in FAST_FACTORS.items():
        for p in params:
            fn = FACTOR_FACTORY[fname](p)
            row = {"factor": fname, "param": str(p), "params_detail": {"n": p}}
            line = f"{fname:<22} {p:>10} |"
            for fwd in FORWARD_PERIODS:
                ics = compute_ic_series(fn, fwd)
                st = ic_stats(ics)
                row[f"ic_{fwd}d"] = st["ic"]
                row[f"ir_{fwd}d"] = st["ir"]
                if st["ic"] is not None:
                    line += f" {st['ic']:>+8.5f} {st['ir']:>6.2f} |"
                else:
                    line += f" {'N/A':>8} {'N/A':>6} |"
            print(line)
            results.append(row)
            done += 1

    # vol_ratio 双参数
    for s, l in VOL_RATIO_GRID:
        fn = make_vol_ratio(s, l)
        row = {"factor": "vol_ratio", "param": f"S{s}_L{l}", "params_detail": {"short": s, "long": l}}
        line = f"{'vol_ratio':<22} {'S'+str(s)+'_L'+str(l):>10} |"
        for fwd in FORWARD_PERIODS:
            ics = compute_ic_series(fn, fwd)
            st = ic_stats(ics)
            row[f"ic_{fwd}d"] = st["ic"]
            row[f"ir_{fwd}d"] = st["ir"]
            if st["ic"] is not None:
                line += f" {st['ic']:>+8.5f} {st['ir']:>6.2f} |"
            else:
                line += f" {'N/A':>8} {'N/A':>6} |"
        print(line)
        results.append(row)
        done += 1

    # 复合因子
    for rn, vn in COMPOSITE_GRID["risk_adj_momentum" if "risk_adj_momentum" in COMPOSITE_GRID else "risk_adj_mom"]:
        fn = make_risk_adj_momentum(rn, vn)
        row = {"factor": "risk_adj_mom", "param": f"R{rn}_V{vn}", "params_detail": {"ret_n": rn, "vol_n": vn}}
        line = f"{'risk_adj_mom':<22} {'R'+str(rn)+'_V'+str(vn):>10} |"
        for fwd in FORWARD_PERIODS:
            ics = compute_ic_series(fn, fwd)
            st = ic_stats(ics)
            row[f"ic_{fwd}d"] = st["ic"]
            row[f"ir_{fwd}d"] = st["ir"]
            if st["ic"] is not None:
                line += f" {st['ic']:>+8.5f} {st['ir']:>6.2f} |"
            else:
                line += f" {'N/A':>8} {'N/A':>6} |"
        print(line)
        results.append(row)
        done += 1

    for w in COMPOSITE_GRID["vol_price_diverge"]:
        fn = make_volume_price_diverge(w)
        row = {"factor": "vol_price_diverge", "param": str(w), "params_detail": {"window": w}}
        line = f"{'vol_price_diverge':<22} {w:>10} |"
        for fwd in FORWARD_PERIODS:
            ics = compute_ic_series(fn, fwd)
            st = ic_stats(ics)
            row[f"ic_{fwd}d"] = st["ic"]
            row[f"ir_{fwd}d"] = st["ir"]
            if st["ic"] is not None:
                line += f" {st['ic']:>+8.5f} {st['ir']:>6.2f} |"
            else:
                line += f" {'N/A':>8} {'N/A':>6} |"
        print(line)
        results.append(row)
        done += 1

    for n in COMPOSITE_GRID["mean_reversion_z"]:
        fn = make_mean_reversion_zscore(n)
        row = {"factor": "mean_reversion_z", "param": str(n), "params_detail": {"n": n}}
        line = f"{'mean_reversion_z':<22} {n:>10} |"
        for fwd in FORWARD_PERIODS:
            ics = compute_ic_series(fn, fwd)
            st = ic_stats(ics)
            row[f"ic_{fwd}d"] = st["ic"]
            row[f"ir_{fwd}d"] = st["ir"]
            if st["ic"] is not None:
                line += f" {st['ic']:>+8.5f} {st['ir']:>6.2f} |"
            else:
                line += f" {'N/A':>8} {'N/A':>6} |"
        print(line)
        results.append(row)
        done += 1

    elapsed = time.time() - t0
    print(f"\n快速因子完成: {done} 组参数, 耗时 {elapsed:.1f}s")
    return results


def run_vmd_factors() -> list[dict]:
    """VMD 因子网格搜索（K × alpha），多进程 + 日粒度。"""
    results = []
    total = len(VMD_K_GRID) * len(VMD_ALPHA_GRID)
    done = 0
    t0 = time.time()

    print(f"\n{'='*100}")
    print(f"VMD 因子网格搜索（K={VMD_K_GRID}, α={VMD_ALPHA_GRID}, window={VMD_WINDOW}）")
    print(f"共 {total} 组参数 × 4 因子 | 采样间隔={VMD_REBALANCE}日 | tol={VMD_TOL} | workers={VMD_WORKERS or 'auto'}")
    print(f"{'='*100}")
    header = f"{'因子':<24} {'K':>3} {'α':>6} | {'IC_5d':>8} {'IR_5d':>6} | {'IC_10d':>8} {'IR_10d':>6} | {'IC_20d':>8} {'IR_20d':>6}"
    print(header)
    print("-" * 100)

    for k in VMD_K_GRID:
        for alpha in VMD_ALPHA_GRID:
            batch = vmd_decompose_batch(
                k, alpha, VMD_WINDOW,
                rebalance=VMD_REBALANCE, tol=VMD_TOL, workers=VMD_WORKERS
            )

            for factor_key, factor_label in [
                ("cycle", "vmd_cycle"), ("slope", "vmd_slope"),
                ("period", "vmd_period"), ("broken", "vmd_broken"),
            ]:
                fname = f"{factor_label}_K{k}_a{alpha}"
                row = {"factor": fname, "param": f"K{k}_a{alpha}",
                       "params_detail": {"k": k, "alpha": alpha, "window": VMD_WINDOW}}
                line = f"{factor_label:<24} {k:>3} {alpha:>6} |"

                for fwd in FORWARD_PERIODS:
                    ics = []
                    for t in range(VMD_WINDOW, n_days - fwd, VMD_REBALANCE):
                        if t not in batch:
                            continue
                        fvals, frets = [], []
                        for code, factors in batch[t].items():
                            fv = factors.get(factor_key)
                            if fv is None or not np.isfinite(fv):
                                continue
                            if t + fwd >= len(close_d[code]) or close_d[code][t] <= 0:
                                continue
                            fut_ret = close_d[code][t + fwd] / close_d[code][t] - 1
                            fvals.append(fv)
                            frets.append(fut_ret)
                        if len(fvals) >= 30:
                            rho, _ = spearmanr(fvals, frets)
                            if not np.isnan(rho):
                                ics.append(rho)

                    st = ic_stats(ics)
                    row[f"ic_{fwd}d"] = st["ic"]
                    row[f"ir_{fwd}d"] = st["ir"]
                    if st["ic"] is not None:
                        line += f" {st['ic']:>+8.5f} {st['ir']:>6.2f} |"
                    else:
                        line += f" {'N/A':>8} {'N/A':>6} |"

                print(line)
                results.append(row)

            done += 1
            elapsed = time.time() - t0
            eta = elapsed / done * (total - done)
            print(f"  [{done}/{total}] K={k} α={alpha} ({elapsed:.0f}s, ETA {eta:.0f}s)", flush=True)

    elapsed = time.time() - t0
    print(f"\nVMD 完成: {done} 组参数, 耗时 {elapsed:.1f}s")
    return results


def print_summary(all_results: list[dict]):
    """输出各因子最佳参数汇总。"""
    print(f"\n{'='*100}")
    print("汇总：各因子最佳参数（按 |IC_20d| 排序，Top 30）")
    print(f"{'='*100}")
    print(f"{'排名':>4} {'因子':<28} {'参数':>12} | {'IC_5d':>8} {'IC_10d':>8} {'IC_20d':>8} | {'IR_20d':>7}")
    print("-" * 100)

    # 按 |IC_20d| 排序
    valid = [r for r in all_results if r.get("ic_20d") is not None]
    valid.sort(key=lambda x: abs(x["ic_20d"]), reverse=True)
    for i, r in enumerate(valid[:30], 1):
        ic5 = r.get("ic_5d") or 0
        ic10 = r.get("ic_10d") or 0
        ic20 = r.get("ic_20d") or 0
        ir20 = r.get("ir_20d") or 0
        print(f"{i:>4} {r['factor']:<28} {r['param']:>12} | {ic5:>+8.5f} {ic10:>+8.5f} {ic20:>+8.5f} | {ir20:>7.3f}")

    # 按因子分组最佳
    print(f"\n{'='*100}")
    print("各因子族最佳配置:")
    print(f"{'='*100}")
    by_family: dict[str, dict] = {}
    for r in valid:
        # 提取因子族名（去掉参数后缀）
        base = r["factor"].split("_K")[0] if "_K" in r["factor"] else r["factor"]
        if base not in by_family or abs(r["ic_20d"]) > abs(by_family[base].get("ic_20d", 0)):
            by_family[base] = r
    ranked_families = sorted(by_family.values(), key=lambda x: abs(x.get("ic_20d", 0)), reverse=True)
    for r in ranked_families:
        ic20 = r.get("ic_20d") or 0
        ir20 = r.get("ir_20d") or 0
        print(f"  {r['factor']:<28} param={r['param']:>12} | IC_20d={ic20:+.5f} IR={ir20:.3f}")


def main():
    parser = argparse.ArgumentParser(description="全因子 IC 网格搜索")
    parser.add_argument("--no-vmd", action="store_true", help="跳过 VMD 因子（快速）")
    parser.add_argument("--vmd-only", action="store_true", help="只跑 VMD 因子")
    parser.add_argument("--data", type=str, default=None, help="数据文件路径")
    parser.add_argument("--output", type=str, default=None, help="输出 JSON 路径")
    parser.add_argument("--min-days", type=int, default=120, help="股票最少交易日数")
    args = parser.parse_args()

    # 加载数据
    data_file = Path(args.data) if args.data else DATA_FILE
    load_data(data_file, min_days=args.min_days)

    all_results = []

    if not args.vmd_only:
        fast_results = run_fast_factors()
        all_results.extend(fast_results)

    if not args.no_vmd:
        vmd_results = run_vmd_factors()
        all_results.extend(vmd_results)

    # 保存完整结果
    out_file = Path(args.output) if args.output else Path("experiment/ic_grid_full.json")
    out_file.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整结果已保存: {out_file} ({len(all_results)} 条)")

    # 汇总
    print_summary(all_results)


if __name__ == "__main__":
    main()
