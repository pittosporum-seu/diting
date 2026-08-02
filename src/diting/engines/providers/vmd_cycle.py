"""谛听 · VMD 周期状态上下文提供者"""

from __future__ import annotations

import numpy as np

from ...infra.config_loader import ConfigLoader
from ...signals.vmd import VMDDecomposer
from .base import ContextProvider


class VmdCycleProvider(ContextProvider):
    """VMD 多尺度周期状态：趋势方向 + 各周期分量的相位和方向。

    参数从 config/diting.yaml 的 context.vmd_cycle_state 段读取。
    """

    def __init__(self):
        cfg = ConfigLoader.get_section("context").get("vmd_cycle_state", {})
        self._k = cfg.get("k", 8)
        self._alpha = cfg.get("alpha", 2000)
        self._window = cfg.get("window", 250)
        self._tol = cfg.get("tol", 1e-5)

    @property
    def name(self) -> str:
        return "vmd_cycle_state"

    def provide(self, code: str, close: np.ndarray, quote=None) -> str | None:
        if len(close) < self._k * 10:
            return None

        state = VMDDecomposer.cycle_state(
            close,
            symbol=code,
            k=self._k,
            alpha=self._alpha,
            window=self._window,
            tol=self._tol,
        )
        if not state or not state.get("cycles"):
            return None

        parts = []
        trend_dir = state.get("trend_dir", "→")
        trend_slope = state.get("trend_slope", 0)
        parts.append(f"趋势{trend_dir}({trend_slope:+.4f})")

        for cyc in state["cycles"]:
            parts.append(f"{cyc['name']}{cyc['dir']}(周期{cyc['period']}天,{cyc['phase_desc']})")

        return "周期状态: " + " | ".join(parts)
