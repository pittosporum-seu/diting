"""精简版 VMD —— 只提取趋势分量 u[0]，跳过不需要的存储和计算。

相比 vmdpy 原版：
- 不存储 u_hat_plus 全历史（省内存）
- 不返回 omega 轨迹（省计算）
- 支持 max_iter 限制（默认 200，原版 500）
- 支持提前收敛（tol 达标即停）
- 使用 scipy.fft（支持 workers 并行 FFT）

用法：
    from scripts.vmd_fast import vmd_trend
    trend = vmd_trend(close_120, K=3, alpha=2000)
"""
from __future__ import annotations

import numpy as np

try:
    from scipy.fft import fft, ifft, fftshift
except ImportError:
    from numpy.fft import fft, ifft, fftshift


def vmd_trend(f: np.ndarray, K: int = 3, alpha: float = 2000.0,
              tol: float = 1e-5, max_iter: int = 200) -> np.ndarray | None:
    """VMD 精简版：只返回最低频模态（趋势分量）。

    Args:
        f: 输入信号（收盘价序列），长度 N
        K: 模态数
        alpha: 带宽约束
        tol: 收敛精度
        max_iter: 最大迭代次数

    Returns:
        趋势分量 u[0]，长度 N-1（或 None 如果失败）
    """
    f = np.asarray(f, dtype=float)
    N = len(f)
    if N < K * 10:
        return None

    # 镜像填充（与原版一致）
    if N % 2:
        f = f[:-1]
        N = len(f)
    ltemp = N // 2
    f_mirr = np.concatenate([f[:ltemp][::-1], f, f[-ltemp:][::-1]])
    T = len(f_mirr)

    # 频域离散化
    freqs = np.arange(1, T + 1) / T - 0.5 - 1.0 / T

    # 构造 f_hat（单边谱）
    f_hat = fftshift(fft(f_mirr))
    f_hat_plus = f_hat.copy()
    f_hat_plus[:T // 2] = 0

    # 初始化
    Alpha = alpha * np.ones(K)

    # 中心频率初始化（均匀分布）
    omega_plus = np.zeros((max_iter, K))
    for i in range(K):
        omega_plus[0, i] = (0.5 / K) * i

    # 只保留当前迭代的 u_hat（不存全历史）
    u_hat_plus = np.zeros((T, K), dtype=complex)
    lambda_hat = np.zeros(T, dtype=complex)

    u_diff = tol + np.spacing(1)
    n = 0
    sum_uk = 0

    # 主循环
    while u_diff > tol and n < max_iter - 1:
        n += 1
        u_diff = 0

        # 更新每个模态
        for k in range(K):
            # 维纳滤波
            numerator = f_hat_plus - sum_uk + lambda_hat / 2.0
            # 排除当前模态的贡献
            sum_other = np.sum(u_hat_plus, axis=1) - u_hat_plus[:, k]
            numerator = f_hat_plus - sum_other + lambda_hat / 2.0

            denom = 1.0 + Alpha[k] * (freqs - omega_plus[n - 1, k]) ** 2
            u_hat_plus[:, k] = numerator / denom

            # 更新中心频率
            freq_sq = freqs[T // 2:] ** 2
            omega_plus[n, k] = np.dot(freq_sq, np.abs(u_hat_plus[T // 2:, k]) ** 2) / \
                np.sum(np.abs(u_hat_plus[T // 2:, k]) ** 2)

        # 更新对偶变量
        lambda_hat = lambda_hat + 0.0 * (f_hat_plus - np.sum(u_hat_plus, axis=1))

        # 收敛判断
        u_hat_new = np.sum(u_hat_plus, axis=1)
        u_diff = np.sum(np.abs(u_hat_new - sum_uk) ** 2) / T if n > 1 else tol + 1
        sum_uk = u_hat_new

    # 提取 u[0]（最低频模态）
    u0_hat = u_hat_plus[:, 0]
    # 恢复双边谱
    u0_hat_full = np.zeros(T, dtype=complex)
    u0_hat_full[T // 2:] = u0_hat[T // 2:]
    u0_hat_full[:T // 2] = np.conj(u0_hat[T // 2:][::-1][:T // 2])

    u0 = np.real(ifft(fftshift(u0_hat_full)))
    # 去掉镜像部分，取中间 N 个点
    u0 = u0[ltemp:ltemp + N]

    # 原版 VMD 输出比输入短 1
    return u0[:N - 1] if len(u0) >= N - 1 else u0


def vmd_factors_fast(f: np.ndarray, K: int = 3, alpha: float = 2000.0,
                     tol: float = 1e-5, max_iter: int = 200) -> dict | None:
    """VMD + 因子提取一体化（精简版）。

    Returns:
        {"cycle": float, "slope": float, "period": float, "broken": float} or None
    """
    trend = vmd_trend(f, K=K, alpha=alpha, tol=tol, max_iter=max_iter)
    if trend is None or len(trend) < 8:
        return None

    factors = {}

    # cycle_position
    if len(trend) >= 4:
        phase = np.angle(np.fft.fft(trend))[1]
        factors["cycle"] = float((np.sin(phase) + 1) / 2)

    # trend_slope (归一化)
    slope = np.polyfit(range(len(trend)), trend, 1)[0]
    avg = trend.mean()
    factors["slope"] = slope / avg if avg > 0 else None

    # dominant_period
    fft_abs = np.abs(np.fft.fft(trend - trend.mean()))
    freqs = np.fft.fftfreq(len(trend))
    pos = freqs > 0
    if pos.any():
        idx = np.argmax(fft_abs[pos])
        freq = freqs[pos][idx]
        factors["period"] = float(1 / freq) if freq > 0 else float(len(trend))
    else:
        factors["period"] = float(len(trend))

    # trend_broken
    if len(trend) >= 10:
        recent_dir = np.sign(trend[-1] - trend[-5])
        overall_dir = np.sign(slope)
        factors["broken"] = float(recent_dir != overall_dir)
    else:
        factors["broken"] = 0.0

    return factors


# ── 基准测试 ──────────────────────────────────────────
if __name__ == "__main__":
    import time

    np.random.seed(42)
    # 模拟 120 天收盘价
    price = 10 + np.cumsum(np.random.randn(120) * 0.1)

    # 原版 vmdpy
    from vmdpy import VMD
    t0 = time.perf_counter()
    for _ in range(100):
        u, _, _ = VMD(price, 2000, 0.0, 3, 0, 1, 1e-7)
    t_orig = (time.perf_counter() - t0) / 100

    # 精简版
    t0 = time.perf_counter()
    for _ in range(100):
        trend = vmd_trend(price, K=3, alpha=2000, tol=1e-5, max_iter=200)
    t_fast = (time.perf_counter() - t0) / 100

    # 精简版 + 因子提取
    t0 = time.perf_counter()
    for _ in range(100):
        factors = vmd_factors_fast(price, K=3, alpha=2000, tol=1e-5, max_iter=200)
    t_full = (time.perf_counter() - t0) / 100

    print(f"原版 vmdpy (tol=1e-7):  {t_orig*1000:.2f} ms/call")
    print(f"精简版 (tol=1e-5):      {t_fast*1000:.2f} ms/call  ({t_orig/t_fast:.1f}x)")
    print(f"精简版+因子提取:        {t_full*1000:.2f} ms/call  ({t_orig/t_full:.1f}x)")
    print(f"\n因子值: {factors}")
    print(f"原版 u[0][:5]: {u[0][:5]}")
    print(f"精简版 [:5]:   {trend[:5]}")
