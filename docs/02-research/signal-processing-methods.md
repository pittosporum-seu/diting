# 信号处理方法增强A股择时

> 2026-07-04 综合调研

## 推荐架构：三层信号处理

```
Layer 0: 小波去噪(sym8) → 去除高频噪声
Layer 1: CEEMDAN(趋势) + VMD(周期) + FFT(验证)
Layer 2: 信号融合 = 35%趋势 + 35%周期 + 30%RSI
```

## 方法对比

| 方法 | 最佳用途 | A股适用性 | 计算耗时 | Python库 |
|------|---------|-----------|---------|---------|
| **VMD** | 周期提取 | ⭐⭐⭐⭐⭐ | 1-3秒 | vmdpy |
| **小波** | 去噪预处理 | ⭐⭐⭐⭐ | <5ms | PyWavelets |
| **CEEMDAN** | 趋势提取 | ⭐⭐⭐⭐ | 2-10秒 | PyEMD |
| **FFT** | 周期验证 | ⭐⭐⭐ | <5ms | scipy.fft |

## VMD关键参数

```python
K=6         # 模态数（典型5-7）
alpha=2000  # 带宽约束
tau=0       # 无噪声容忍
DC=0        # 第一个模态不放直流
init=1      # 均匀初始化
tol=1e-7    # 收敛容限
```

## 计算复杂度

| 模块 | 时间复杂度 | 252天数据耗时 | 实时性 |
|------|-----------|-------------|--------|
| 小波去噪 | O(N log N) | <5ms | ✅ 实时 |
| FFT周期 | O(N log N) | <5ms | ✅ 实时 |
| CEEMDAN | O(N×trials×log N) | 2-10秒 | ⚠️ 需缓存 |
| VMD | O(N×K×iterations) | 1-3秒 | ⚠️ 需缓存 |

**优化：** 每日收盘后批量预计算，存入缓存。

## 学术来源

- VMD: Dragomiretskiy & Zosso (2014)
- CEEMDAN: Torres et al. (2011)
- 小波去噪: Donoho & Johnstone (1994)

## VMD 回测常见 Bug

1. **参数顺序**：`VMD(signal, alpha, tau, K, DC, init, tol)` — tau/K 互换会报 index error
2. **输出长度**：`len(u[0]) = len(input) - 1`，遍历时注意边界
3. **内存泄漏**：每次调用后 `del u, _, om` + `gc.collect()`
4. **窗口约束**：`vmd_window >= K * 10`
