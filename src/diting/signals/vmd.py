"""谛听 · VMD 变分模态分解

基于 vmdpy 实现，用于识别市场周期和趋势。
"""

from __future__ import annotations

import gc
from datetime import datetime

import numpy as np
from numpy import ndarray

from ..infra.config_loader import ConfigLoader
from ..infra.errors import DataUnavailableError
from ..infra.logging_config import get_logger
from ..schema import VMDResult

logger = get_logger(__name__)


class VMDDecomposer:
    """VMD 分解器。

    将价格序列分解为 k 个模态分量，识别主导周期和趋势。
    """

    # 默认参数（经验调优）
    DEFAULT_K = 6
    DEFAULT_ALPHA = 2000

    @classmethod
    def _vmd_config(cls) -> dict:
        return ConfigLoader.get_section("indicators").get("vmd", {})

    @classmethod
    def decompose(
        cls,
        close: ndarray,
        symbol: str = "",
        k: int | None = None,
        alpha: int | None = None,
    ) -> VMDResult:
        """对收盘价序列执行 VMD 分解。

        Args:
            close: 收盘价序列，长度必须 >= k * 10
            symbol: 股票代码（用于日志）
            k: 模态数
            alpha: 带宽约束参数

        Returns:
            VMDResult @dataclass
        """
        cfg = cls._vmd_config()
        if k is None:
            k = cfg.get("k", cls.DEFAULT_K)
        if alpha is None:
            alpha = cfg.get("alpha", cls.DEFAULT_ALPHA)

        if len(close) < k * 10:
            raise DataUnavailableError(f"VMD needs >= {k * 10} rows, got {len(close)}")

        try:
            from vmdpy import VMD

            tau = 0.0
            dc = 0
            init = 1
            tol = 1e-7

            u, _, _ = VMD(close, alpha, tau, k, dc, init, tol)

            # VMD 输出比输入短 1
            trend = u[0]  # 最低频 = 趋势分量

            # 周期位置：最低频模态的相位
            if len(trend) >= 2:
                phase = np.angle(np.fft.fft(trend))[1]
                cycle_position = float((np.sin(phase) + 1) / 2)  # 0~1
            else:
                cycle_position = 0.5

            # 趋势斜率
            if len(trend) >= 5:
                trend_slope = float(np.polyfit(range(len(trend)), trend, 1)[0])
            else:
                trend_slope = 0.0

            # 主导周期：低频分量 FFT 主频
            if len(trend) >= 4:
                fft = np.abs(np.fft.fft(trend))
                freqs = np.fft.fftfreq(len(trend))
                positive_mask = freqs > 0
                if positive_mask.any():
                    dominant_idx = np.argmax(fft[positive_mask])
                    dominant_freq = freqs[positive_mask][dominant_idx]
                    dominant_period = int(1 / dominant_freq) if dominant_freq > 0 else len(trend)
                else:
                    dominant_period = len(trend)
            else:
                dominant_period = len(trend)

            # 趋势是否被打破（近 5 个点背离趋势方向）
            trend_broken = False
            if len(trend) >= 10:
                recent_direction = np.sign(trend[-1] - trend[-5])
                overall_direction = np.sign(trend_slope)
                trend_broken = bool(recent_direction != overall_direction)

            logger.info(
                "vmd.done",
                symbol=symbol,
                k=k,
                cycle_position=round(cycle_position, 3),
                trend_slope=round(trend_slope, 4),
            )

        except Exception as e:
            logger.error("vmd.failed", symbol=symbol, error=str(e))
            raise DataUnavailableError(f"VMD failed: {e}") from e
        finally:
            # 防止 VMD 内存泄漏
            gc.collect()

        return VMDResult(
            symbol=symbol,
            cycle_position=round(cycle_position, 4),
            trend_slope=round(trend_slope, 6),
            dominant_period=dominant_period,
            trend_broken=trend_broken,
            timestamp=datetime.now(),
            params={"k": k, "alpha": alpha},
        )

    @classmethod
    def cycle_state(
        cls,
        close: ndarray,
        symbol: str = "",
        k: int | None = None,
        alpha: int | None = None,
        window: int = 250,
        tol: float = 1e-5,
    ) -> dict | None:
        """提取多尺度周期状态（用于 AI 上下文）。

        跳过 u[0] 趋势分量，从 u[1:] 提取各周期的方向、相位、周期长度。

        Returns:
            {
                "trend_dir": "↑"/"↓"/"→",
                "trend_slope": float,
                "cycles": [
                    {"name": "半年", "period": 125, "phase": 0.3,
                     "phase_desc": "上升段", "dir": "↑"},
                    ...
                ]
            }
            失败返回 None。
        """
        cfg = cls._vmd_config()
        if k is None:
            k = cfg.get("k", 8)
        if alpha is None:
            alpha = cfg.get("alpha", cls.DEFAULT_ALPHA)

        # 取最近 window 天
        seg = close[-window:] if len(close) >= window else close
        if len(seg) < k * 10:
            return None

        try:
            from vmdpy import VMD

            u, _, _ = VMD(seg, alpha, 0.0, k, 0, 1, tol)
        except Exception:
            return None
        finally:
            gc.collect()

        price_scale = float(seg.mean())
        state: dict = {"cycles": []}

        # u[0] 趋势方向
        trend = u[0]
        if len(trend) >= 5:
            slope = float(np.polyfit(range(5), trend[-5:], 1)[0])
            norm_slope = slope / price_scale if price_scale > 0 else 0.0
            state["trend_slope"] = round(norm_slope, 5)
            state["trend_dir"] = (
                "↑" if norm_slope > 0.0005 else ("↓" if norm_slope < -0.0005 else "→")
            )
        else:
            state["trend_slope"] = 0.0
            state["trend_dir"] = "→"

        # u[1:] 周期分量
        cycle_names = {1: "半年", 2: "月度", 3: "双周", 4: "周级", 5: "短周期"}
        for i in range(1, min(k, len(u), 6)):
            imf = u[i]
            if len(imf) < 8:
                continue

            # 主周期（FFT）
            fft_abs = np.abs(np.fft.rfft(imf - imf.mean()))
            freqs = np.fft.rfftfreq(len(imf), d=1.0)
            if len(fft_abs) <= 1:
                continue
            peak_idx = int(np.argmax(fft_abs[1:]) + 1)
            peak_freq = freqs[peak_idx]
            period = round(1.0 / peak_freq) if peak_freq > 0 else len(imf)

            # 相位（Hilbert）
            analytic = np.fft.ifft(np.fft.fft(imf) * 2)
            phase = float((np.angle(analytic)[-1] / (2 * np.pi) + 0.5) % 1.0)

            # 方向（最近 5 天斜率）
            sl = float(np.polyfit(range(5), imf[-5:], 1)[0]) if len(imf) >= 5 else 0.0
            direction = "↑" if sl > 0 else "↓"

            # 相位描述
            if phase < 0.25:
                phase_desc = "谷底回升"
            elif phase < 0.5:
                phase_desc = "上升段"
            elif phase < 0.75:
                phase_desc = "接近顶部"
            else:
                phase_desc = "回落段"

            state["cycles"].append({
                "name": cycle_names.get(i, f"IMF{i}"),
                "period": period,
                "phase": round(phase, 2),
                "phase_desc": phase_desc,
                "dir": direction,
            })

        return state
