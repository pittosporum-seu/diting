# 策略研究与生产晋升设计

## 背景

历史扫描逻辑把探索性权重直接放进生产路径，研究数据、因子版本和真实收益验证又没有
形成完整证据链。v0.8 将“发现候选”和“生产激活”分开：研究可以快速迭代，但只有通过
固定样本外门槛且经 owner 批准的版本才能被 `ScanOrchestrator` 读取。

## 研究数据流

```text
Data Gateway (point-in-time, provider traces)
  -> immutable research snapshot + snapshot hash
  -> factor computation (versioned)
  -> train-only direction/selection/weights
  -> validation + OOS evaluation + costs
  -> ExperimentManifest + compact metrics
  -> strategy registry: draft -> validated -> approved -> active
```

研究脚本与生产代码使用相同的规范化数据协议，但研究缓存键必须额外包含实验、因子和
数据版本。原始 DataFrame 只存在于适配器和计算函数局部，不作为跨模块协议。

## ExperimentManifest 最小字段

- 实验 ID、创建时间、代码 commit、配置哈希、随机种子；
- 数据起止、Provider trace、复权方式、Schema 版本、快照哈希；
- point-in-time 证券池规则、上市/退市日期、覆盖率和排除原因；
- 因子名称/参数/实现版本、训练方向、去冗余选择和最终权重；
- train/validation/OOS 指标、交易成本、bootstrap 区间和参数稳健性；
- 所有晋升门槛的 pass/fail 与失败原因。

## mean_reversion_v1 候选

候选因子族固定为：

| 因子族 | 研究目的 |
|---|---|
| `price_vs_ma_N` | 中期价格相对均值的偏离 |
| `ret_N` | 中期收益/回撤幅度 |
| `volatility_N` | 风险与反弹质量 |
| `rsi_N` | 超买超卖状态 |
| `vol_ratio_N` | 成交量确认与缩量 |
| `boll_pos_N` | 波动带中的相对位置 |

参数、方向和权重不是文档常量：只在训练集计算。绝对相关性大于 0.7 的因子对只保留
训练 IC_IR 更高者；最终按训练 IC_IR 归一，任一因子权重不超过 35%。VMD、AI 分和
`dist_high_20` 不进入生产排名。

## 验证窗口与组合

| 阶段 | 日期 |
|---|---|
| Train | 2022-01-01 至 2024-12-31 |
| Validation | 2025-01-01 至 2025-12-31 |
| OOS | 2026-01-01 至 2026-07-31 |

- 每个调仓日使用当时可交易股票池，至少 500 只；
- Top20 等权，持有 20 个交易日；
- 往返成本 40bp；停牌、涨跌停和不可交易情况必须按 manifest 规则处理；
- 训练集之外不得重新选择方向、参数或权重。

## 晋升门槛

- OOS Rank IC ≥ 0.05；
- OOS IC_IR ≥ 0.5；
- 95% bootstrap IC 下界 > 0；
- 净 20 日超额 ≥ 0.5%；
- 相邻参数指标变化 <30%；
- 数据覆盖 ≥90%；
- 无未来数据泄漏。

全部满足只允许转为 validated。owner 审阅报告后才能 approved，再通过显式命令/API
切换 active。任何门槛失败都保留报告，但机会榜不得使用该候选。

## VMD 的位置

已有实验显示 VMD 横截面预测力约处于弱信号边缘，且样本稳定性不足。v0.8 保留它用于：

- 解释当前周期结构；
- 为结构化 LLM 引擎提供证据；
- 后续独立研究。

它不参与 `mean_reversion_v1` 打分，不因某次参数搜索的局部最优而获得生产权重。
