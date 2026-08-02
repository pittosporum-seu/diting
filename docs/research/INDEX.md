# 谛听策略研究索引

> 当前研究目标是为 v0.8.0 建立可复现、可审批、可追溯的生产策略治理。历史实验只提供
> 假设与证据，未经新门槛验证不得直接进入生产。

## 文档

| 文档 | 类型 | 用途 |
|---|---|---|
| [design.md](design.md) | Explanation | 研究边界、数据流、因子与晋升原则 |
| [experiments.md](experiments.md) | Research log | 历史实验、局限和结论 |
| [roadmap.md](roadmap.md) | How-to plan | `mean_reversion_v1` 验证与激活顺序 |
| `research/artifacts/**/manifest.json` | Reference | 可复现实验输入、版本、哈希和指标 |

## 已确认结论

- 历史 `dist_high_20: 0.85` 生产权重没有足够真实收益证据，v0.8 必须移除。
- 现有 298 只、约 2 年样本提示 A 股 20 日维度均值回归强于追涨，但样本存在存活偏差、
  覆盖不足和窗口过短，不能直接作为生产批准依据。
- VMD 全量验证已完成；横截面预测力偏弱，最佳 Rank IC 约 0.05，且稳健性不足。
  v0.8 中 VMD 只作为 AI 上下文/证据，生产排名权重为 0。
- `mean_reversion_v1` 只使用 price-vs-MA、return、volatility、RSI、volume ratio 和
  Bollinger 候选族；方向和权重只由训练集决定。

## 当前状态

| 项目 | 状态 |
|---|---|
| 历史实验归档 | 已完成；原始 106 MB 文件位于仓库外归档 |
| ExperimentManifest/策略注册表 | v0.8 已实现并由迁移、审计和 Owner API 保护 |
| point-in-time 研究数据集 | 待通过 Data Gateway 重建 |
| `mean_reversion_v1` | draft，尚未 validated/approved/active |
| 生产机会榜 | 新策略激活前必须返回 `NO_ACTIVE_STRATEGY` |

## 会话恢复规则

1. 先读本页和 `tasks/todo.md`。
2. 研究实现不得绕过 Data Gateway。
3. 每次实验写 manifest 和精简 JSON，再向 `experiments.md` 追加结论。
4. 只有完整通过 `roadmap.md` 的门槛才能进入 validated；人工批准/激活另行执行。

## 进展日志

| 日期 | 进展 | 结论 |
|---|---|---|
| 2026-07-28 | 旧因子 IC/回测 | 均值回归候选优于旧追涨权重，但样本不足 |
| 2026-08-01 | VMD 全量验证 | 预测力弱，只保留为上下文 |
| 2026-08-02 | v0.8 设计 Accepted | 建立严格研究生命周期和生产激活门槛 |
| 2026-08-02 | v0.8 治理代码完成 | manifest、门槛、候选因子、active-only 扫描已实现；未伪造研究通过或 active 状态 |
