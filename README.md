# 谛听 (Diting)

> 🐾 A股多模型AI投资分析工具 — 聆听市场多维度信号

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)

---

## 是什么

谛听是一款开源的A股投资分析工具，融合多种经典分析流派（Wyckoff、Buffett/Munger、CANSLIM、Volume Profile），通过AI + Python沙箱进行计算，输出多引擎共识评分和可视化报告。

## 快速开始

```bash
# 安装
pip install diting

# L0: 快速行情快照
diting l0 --symbols 002475,603659

# L1: 标准分析 + AI解读
diting l1 --symbols 002475 --engines wyckoff,vmd_rsi

# L2: 深度分析 + 多引擎共识
diting l2 --watchlist config/watchlist.csv --notify feishu,email
```

## 三档层级

| 层级 | 能力 | AI | 适用场景 |
|------|------|:--:|------|
| L0 | 行情快照+简单指标 | ❌ | 盘中快速扫一眼 |
| L1 | +AI解读+信号处理 | ✅ | 日常分析 |
| L2 | +多引擎共识+深度报告 | ✅ | 周末复盘 |

## 分析引擎

- **Wyckoff（威克夫）** — Phase A-E 阶段识别 + Spring/SOS 信号
- **Buffett/Munger** — 100分综合评分 + 8项财报预警
- **CANSLIM** — 七维成长股评分
- **Volume Profile** — VAH/POC/VAL + 支撑压力
- **VMD+RSI 择时** — 三维择时（大盘×行业×个股）

## 项目状态

🟢 **M1 骨架完成** — 22 tests ✅ · ruff ✅ · CLI ✅ | 下一步 M2 数据层

- 📐 [架构设计](docs/01-design/architecture.md)
- 📋 [功能设计](docs/01-design/features.md)
- 📊 [数据模型](docs/01-design/data-models.md)
- 🔌 [API 契约](docs/01-design/api-contracts.md)
- 🗺️ [路线图](ROADMAP.md)

## 许可

MIT License
