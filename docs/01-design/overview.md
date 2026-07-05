# 谛听 · 架构概览

> 🐾 A股多模型AI投资分析工具 — 聆听市场多维度信号
> 版本 v2.0 | 2026-07-05 | 审查通过 ✅ | MIT 开源

---

## 项目速览

| 项目 | 详情 |
|------|------|
| 定位 | A股多模型AI投资分析工具 · 开源 Python 库 |
| 许可 | MIT |
| Python | 3.12+ |
| 包管理 | uv + pyproject.toml |
| 安装 | `pip install diting` |
| 飞书文档 | [谛听 · 架构全景](https://my.feishu.cn/docx/CI3hdibfNolTD0x2B4Kc7q1unjf) |

---

## 六层架构

```
Layer 5: Presentation — CLI (click) · REST API (FastAPI) · Cron
Layer 4: Orchestration — AnalysisPipeline 管道编排
Layer 3: Analysis — Wyckoff · Buffett/Munger · CANSLIM · Volume Profile · VMD+RSI
Layer 2: Signal Processing — VMD · CEEMDAN · Wavelet · Technical Indicators
Layer 1: Data Access — mx-data → akshare → SQLite 三级降级
Layer 0: Infrastructure — Config · structlog · Metrics · Error Hierarchy
```

**铁律：下层永远不 import 上层。**

---

## 五大分析引擎

| 引擎 | 方法 | 驱动方式 |
|------|------|---------|
| Wyckoff | Phase A-E 阶段识别 | AI + 沙箱 |
| Buffett/Munger | 100分综合评分 + 8项财报预警 | AI + 沙箱 |
| CANSLIM | 七维成长股评分 | AI + 沙箱 |
| Volume Profile | VAH/POC/VAL | 纯计算 |
| VMD+RSI 择时 | 三维择时（大盘×行业×个股） | 纯计算 |

---

## 三档层级

| 层级 | 能力 | AI | 耗时 |
|------|------|:--:|:---:|
| L0 | 行情快照+简单指标 | ❌ | <5s |
| L1 | +AI解读+信号处理 | V4 Flash | 30-90s |
| L2 | +多引擎共识+深度报告 | V4 Pro | 3-5min |

---

## 技术选型

- **AI**: LiteLLM（100+ provider 统一接口）
- **沙箱**: sandboxmcp（seccomp + namespace 隔离）
- **图表**: ECharts（309KB，iPad 兼容）
- **日志**: structlog

---

## 路线图

23 个 Issue，6 个 Milestone：骨架 → 数据 → 信号 → 沙箱+引擎 → 全引擎 → 发布。

**当前状态：🟢 设计完成，即将进入 Sprint 1。**

---

*详细设计见 [architecture.md](architecture.md)，飞书文档见 [谛听 · 架构全景](https://my.feishu.cn/docx/CI3hdibfNolTD0x2B4Kc7q1unjf)*
