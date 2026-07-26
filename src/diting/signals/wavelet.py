"""谛听 · 小波去噪 + CEEMDAN 趋势提取"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..infra.logging_config import get_logger

logger = get_logger(__name__)


class WaveletDenoiser:
    """小波去噪器 — sym8 小波软阈值去噪"""

    @classmethod
    def denoise(cls, signal: ndarray, wavelet: str = "sym8", level: int = 4) -> ndarray:
        """
        Args:
            signal: 输入信号（价格序列）
            wavelet: 小波类型，默认 sym8
            level: 分解层数
        Returns:
            去噪后的信号（与输入等长）
        """
        import pywt

        signal = np.asarray(signal, dtype=float).copy()  # 确保可写

        if len(signal) < 2**level:
            level = max(1, int(np.log2(len(signal))))
            logger.debug("wavelet.adjust_level", new_level=level)

        # 小波分解
        coeffs = pywt.wavedec(signal, wavelet, level=level)

        # 软阈值去噪（保留最低频）
        sigma = np.median(np.abs(coeffs[-1])) / 0.6745 if len(coeffs) > 1 else 0.1
        threshold = sigma * np.sqrt(2 * np.log(len(signal)))

        denoised_coeffs = [coeffs[0]]  # 低频保留
        for c in coeffs[1:]:
            denoised_coeffs.append(pywt.threshold(c, threshold, mode="soft"))

        # 重建
        denoised = pywt.waverec(denoised_coeffs, wavelet)
        # 截断到原始长度
        if len(denoised) > len(signal):
            denoised = denoised[: len(signal)]

        logger.info("wavelet.done", length=len(signal), wavelet=wavelet)
        return denoised


class CEEMDANDecomposer:
    """CEEMDAN 自适应趋势提取"""

    @classmethod
    def extract_trend(cls, signal: ndarray) -> ndarray:
        """提取趋势分量（最低频模态之和）

        Returns:
            与输入等长的趋势线
        """
        from PyEMD import CEEMDAN

        if len(signal) < 10:
            logger.warning("ceemdan.too_short", length=len(signal))
            return signal

        ceemdan = CEEMDAN()
        imfs = ceemdan(signal)

        # 取后 2~3 个低频 IMF 作为趋势
        n_trend = max(1, min(3, len(imfs) // 2))
        trend = np.sum(imfs[-n_trend:], axis=0)

        if len(trend) < len(signal):
            trend = np.pad(trend, (0, len(signal) - len(trend)), "edge")

        logger.info("ceemdan.done", length=len(signal), n_imfs=len(imfs))
        return trend
