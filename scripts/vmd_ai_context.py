"""VMD 周期状态 → AI 引擎上下文增强原型。

验证：给 AI 引擎加入 VMD 多尺度周期描述后，分析质量是否提升。
"""
from __future__ import annotations

import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from diting.config import Config
Config()


def vmd_cycle_state(close: np.ndarray, K: int = 8, alpha: float = 2000.0,
                    tol: float = 1e-5) -> dict | None:
    """提取 VMD 多尺度周期状态（用于 AI 上下文）。

    Returns:
        {
            "trend_dir": "↑"/"↓"/"→",
            "trend_slope": float,
            "cycles": [
                {"name": "半年", "period": 125, "phase": 0.3, "dir": "↑"},
                {"name": "月度", "period": 35, "phase": 0.7, "dir": "→"},
                ...
            ]
        }
    """
    from vmdpy import VMD

    N = len(close)
    if N < K * 10:
        return None

    try:
        u, _, _ = VMD(close, alpha, 0.0, K, 0, 1, tol)
    except Exception:
        return None

    price_scale = close.mean()
    state = {"cycles": []}

    # u[0] 趋势
    trend = u[0]
    if len(trend) >= 5:
        slope = np.polyfit(range(5), trend[-5:], 1)[0]
        norm_slope = slope / price_scale if price_scale > 0 else 0
        state["trend_slope"] = round(norm_slope, 5)
        state["trend_dir"] = "↑" if norm_slope > 0.0005 else ("↓" if norm_slope < -0.0005 else "→")

    # u[1:] 周期分量
    cycle_names = {1: "半年", 2: "月度", 3: "双周", 4: "周级", 5: "短周期"}
    for i in range(1, min(K, 6)):
        imf = u[i]
        if len(imf) < 8:
            continue

        # 主周期
        fft_abs = np.abs(np.fft.rfft(imf - imf.mean()))
        freqs = np.fft.rfftfreq(len(imf), d=1.0)
        if len(fft_abs) <= 1:
            continue
        peak_idx = np.argmax(fft_abs[1:]) + 1
        peak_freq = freqs[peak_idx]
        period = round(1.0 / peak_freq) if peak_freq > 0 else N

        # 相位（Hilbert）
        analytic = np.fft.ifft(np.fft.fft(imf) * 2)
        phase = float((np.angle(analytic)[-1] / (2 * np.pi) + 0.5) % 1.0)

        # 方向（最近 5 天斜率）
        if len(imf) >= 5:
            sl = np.polyfit(range(5), imf[-5:], 1)[0]
            direction = "↑" if sl > 0 else "↓"
        else:
            direction = "→"

        # 相位描述
        if phase < 0.25:
            phase_desc = "谷底回升"
        elif phase < 0.5:
            phase_desc = "上升段"
        elif phase < 0.75:
            phase_desc = "接近顶部"
        else:
            phase_desc = "回落段"

        name = cycle_names.get(i, f"IMF{i}")
        state["cycles"].append({
            "name": name,
            "period": period,
            "phase": round(phase, 2),
            "phase_desc": phase_desc,
            "dir": direction,
        })

    return state


def format_cycle_context(state: dict) -> str:
    """将周期状态格式化为 AI 可读的紧凑文本。"""
    if not state:
        return ""

    parts = []
    trend_dir = state.get("trend_dir", "→")
    trend_slope = state.get("trend_slope", 0)
    parts.append(f"趋势{trend_dir}({trend_slope:+.4f})")

    for cyc in state.get("cycles", []):
        parts.append(
            f"{cyc['name']}{cyc['dir']}(周期{cyc['period']}天,{cyc['phase_desc']})"
        )

    return "周期状态: " + " | ".join(parts)


def main():
    # 加载数据
    df_all = pd.read_csv("experiment/backtest_data/daily_2022_2024.csv")
    data = {code: group.reset_index(drop=True) for code, group in df_all.groupby("code")}

    # 取几只股票测试
    test_codes = list(data.keys())[:5]
    WINDOW = 250

    print("=" * 80)
    print("VMD 周期状态 → AI 上下文增强原型")
    print("=" * 80)

    for code in test_codes:
        df = data[code]
        close = np.asarray(df["close"], dtype=float)
        if len(close) < WINDOW:
            continue

        seg = close[-WINDOW:]
        state = vmd_cycle_state(seg, K=8, alpha=2000, tol=1e-5)
        context = format_cycle_context(state)

        # 模拟当前 build_summary 的输出
        price = seg[-1]
        chg20 = (seg[-1] / seg[-20] - 1) * 100
        chg5 = (seg[-1] / seg[-5] - 1) * 100

        print(f"\n{'─'*80}")
        print(f"股票: {code}")
        print(f"当前摘要: 现价{price:.2f} 近20日{chg20:+.1f}% 近5日{chg5:+.1f}%")
        print(f"VMD增强:  {context}")

        # 综合判断提示
        if state and state.get("cycles"):
            c1 = state["cycles"][0] if len(state["cycles"]) > 0 else None
            c2 = state["cycles"][1] if len(state["cycles"]) > 1 else None
            if c1 and c2:
                if c1["dir"] == "↑" and c2["dir"] == "↓":
                    print(f"→ 解读: {c1['name']}周期上行 + {c2['name']}回调 = 上升趋势中的回调")
                elif c1["dir"] == "↓" and c2["dir"] == "↑":
                    print(f"→ 解读: {c1['name']}周期下行 + {c2['name']}反弹 = 下降趋势中的反弹")
                elif c1["dir"] == "↑" and c2["dir"] == "↑":
                    print(f"→ 解读: 多周期共振上行")
                elif c1["dir"] == "↓" and c2["dir"] == "↓":
                    print(f"→ 解读: 多周期共振下行")


if __name__ == "__main__":
    main()
