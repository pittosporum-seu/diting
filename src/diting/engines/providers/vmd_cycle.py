"""谛听 · VMD 周期状态上下文提供者"""

from __future__ import annotations

import numpy as np

from ...signals.vmd import VMDDecomposer
from .base import ContextProvider


class VmdCycleProvider(ContextProvider):
    """VMD 多尺度周期状态：趋势方向 + 各周期分量的相位和方向。"""

    @property
    def name(self) -> str:
        return "vmd_cycle_state"

    def provide(self, code: str, close: np.ndarray, quote=None) -> str | None:
        if len(close) < 80:  # 至少需要 K*10 的数据
            return None

        state = VMDDecomposer.cycle_state(close, symbol=code)
        if not state or not state.get("cycles"):
            return None

        parts = []
        trend_dir = state.get("trend_dir", "→")
        trend_slope = state.get("trend_slope", 0)
        parts.append(f"趋势{trend_dir}({trend_slope:+.4f})")

        for cyc in state["cycles"]:
            parts.append(
                f"{cyc['name']}{cyc['dir']}(周期{cyc['period']}天,{cyc['phase_desc']})"
            )

        return "周期状态: " + " | ".join(parts)
