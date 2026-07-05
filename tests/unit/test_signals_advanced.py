"""#11 VMD + #12 小波/CEEMDAN 测试"""

import numpy as np
import pytest

from src.diting.infra.errors import DataUnavailableError
from src.diting.signals.vmd import VMDDecomposer
from src.diting.signals.wavelet import CEEMDANDecomposer, WaveletDenoiser


def make_sine(n=200, noise=0.3):
    """生成带噪正弦测试信号"""
    t = np.linspace(0, 4 * np.pi, n)
    clean = 50 + 10 * np.sin(t) + 5 * np.sin(2 * t)
    noisy = clean + np.random.normal(0, noise, n)
    return noisy, clean


# ═══════════════════════════════════════════
# VMD
# ═══════════════════════════════════════════


class TestVMD:
    def test_decompose_returns_result(self):
        signal, _ = make_sine(n=80)
        result = VMDDecomposer.decompose(signal, symbol="test")
        assert result.symbol == "test"
        assert 0 <= result.cycle_position <= 1
        assert result.dominant_period > 0

    def test_decompose_trend_detection(self):
        """上升趋势 → trend_slope > 0"""
        close = np.linspace(50, 80, 100) + np.random.normal(0, 0.5, 100)
        result = VMDDecomposer.decompose(close, symbol="up")
        assert result.trend_slope > 0

    def test_insufficient_data(self):
        with pytest.raises(DataUnavailableError, match="VMD needs"):
            VMDDecomposer.decompose(np.array([1, 2, 3]), symbol="short")

    def test_cycle_position_range(self):
        signal, _ = make_sine(n=90)
        result = VMDDecomposer.decompose(signal, k=3, alpha=1000)
        assert 0 <= result.cycle_position <= 1

    def test_params_are_recorded(self):
        signal, _ = make_sine(n=80)
        result = VMDDecomposer.decompose(signal, k=4, alpha=3000)
        assert result.params["k"] == 4
        assert result.params["alpha"] == 3000


# ═══════════════════════════════════════════
# Wavelet denoising
# ═══════════════════════════════════════════


class TestWavelet:
    def test_denoise_preserves_length(self):
        signal, _ = make_sine(n=128)
        denoised = WaveletDenoiser.denoise(signal, level=3)
        assert len(denoised) == len(signal)

    def test_denoise_reduces_noise(self):
        signal, clean = make_sine(n=128, noise=2.0)
        denoised = WaveletDenoiser.denoise(signal)
        mse_original = np.mean((signal - clean) ** 2)
        mse_denoised = np.mean((denoised - clean) ** 2)
        assert mse_denoised < mse_original, "denoised should be closer to truth"

    def test_short_signal_adjusts_level(self):
        signal = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        denoised = WaveletDenoiser.denoise(signal, level=4)
        assert len(denoised) == len(signal)


# ═══════════════════════════════════════════
# CEEMDAN
# ═══════════════════════════════════════════


class TestCEEMDAN:
    def test_extract_trend_preserves_length(self):
        signal, _ = make_sine(n=100)
        trend = CEEMDANDecomposer.extract_trend(signal)
        assert len(trend) == len(signal)

    def test_extract_trend_smoother_than_signal(self):
        """趋势线应该比原始信号更平滑"""
        signal, _ = make_sine(n=100, noise=1.5)
        trend = CEEMDANDecomposer.extract_trend(signal)
        sig_std = np.std(np.diff(signal))
        trend_std = np.std(np.diff(trend))
        assert trend_std < sig_std

    def test_short_signal_returns_original(self):
        signal = np.array([1, 2, 3, 4, 5])
        trend = CEEMDANDecomposer.extract_trend(signal)
        assert np.array_equal(trend, signal)
