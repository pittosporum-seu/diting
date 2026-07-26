# 快速筛选指标实验报告

- 样本数: 2（含 AI 全量分析: 2）
- 目标: 最终 6 引擎共识分 (consensus_score)

## 1. 指标相关性排名（vs 共识分，按 |Spearman|）

| 指标 | Pearson | Spearman | N |
|------|---------|----------|---|
| change_pct | None | None | 2 |
| intraday_pos | None | None | 0 |
| amplitude | None | None | 0 |
| open_strength | None | None | 0 |
| rsi_14 | None | None | 2 |
| macd_histogram | None | None | 2 |
| kdj_k | None | None | 2 |
| kdj_d | None | None | 2 |
| kdj_j | None | None | 2 |
| bollinger_position | None | None | 2 |
| vwap_deviation | None | None | 2 |
| volume_ratio | None | None | 2 |
| ma_alignment | None | None | 2 |
| price_vs_ma20 | None | None | 0 |

## 2. 逐步回归（R² 随指标数）

（样本不足，未做回归）

## 3. 排名一致性（快速公式 vs 全量共识）

（样本不足）

## 4. 结论

见上述 R² 与排名一致性：R² 越高、排名 Spearman 越接近 1，
说明快速公式越能逼近全量引擎评分，初筛越有效。