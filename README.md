# 谛听 (Diting)

> 🐾 A股多模型AI投资分析工具 — 聆听市场多维度信号

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![GitHub](https://img.shields.io/badge/GitHub-pittosporum--seu/diting-181717)](https://github.com/pittosporum-seu/diting)

---

## 是什么

谛听是一款开源的A股投资分析工具，融合多种经典分析流派，通过AI + Python沙箱进行计算，输出多引擎共识评分和可视化报告。

## 快速体验

```bash
# 克隆
git clone https://github.com/pittosporum-seu/diting.git
cd diting

# Python 3.12+，需要 uv（推荐）或 pip
uv sync

# 一键分析
uv run diting 002475

# 行情快照（无需 AI）
uv run diting scan 002475

# 详细分析
uv run diting 002475 --more

# HTML 报告
uv run diting 002475 --report

# 多股对比
uv run diting compare 002475,603659

# 自选股概览
uv run diting watchlist

# Web 版
uv run diting serve
```

## 架构

**六层架构，六大引擎：**

```
L5  CLI / Web / Report / Notify
L4  Pipeline / Consensus / Alert
L3  6 Engines (Wyckoff·Buffett·CANSLIM·Vol·VMD+RSI·Verdict)
L2  Signals (RSI·VMD·Wavelet·CEEMDAN)
L1  Data (eltdx → ashare → mx-data → akshare)
L0  Infra (structlog·@cached·@retry)
```

### 六大分析引擎

| 引擎 | 方法 | 驱动方式 |
|------|------|---------|
| **Wyckoff** | Phase A-E 阶段识别 + Spring/SOS | AI + 沙箱 |
| **Buffett/Munger** | 100分综合评分 + 8项财报预警 | AI + 沙箱 |
| **CANSLIM** | 七维成长股评分 | AI + 沙箱 |
| **Volume Profile** | VAH/POC/VAL 支撑压力 | 纯计算 |
| **VMD+RSI** | 三维择时（大盘×行业×个股） | 纯计算 |
| **Verdict** | 信号→人话结论翻译 | 纯计算 |

### 数据源降级链

```
eltdx（通达信直连，0.2s）
  → ashare（新浪/腾讯，免费不限量）
    → mx-data（东方财富，需 API Key）
      → akshare（免费兜底）
```

## 项目状态

🎉 **v0.2.1 — 全量配置化完成**

| 统计 | |
|------|---|
| 测试 | **529 passed** |
| 源码 | 67 个 .py 文件 |
| 引擎 | 6 (5 AI/计算 + 1 结论翻译) |
| 数据源 | 4 级降级链，免费可用 |
| 文档 | 设计文档 + 开发手册 |
| 配置 | config/diting.yaml 驱动全部策略 |

## 设计文档

| 文档 | 说明 |
|------|------|
| [架构设计](docs/01-design/architecture.md) | 六层架构、设计模式、模块协议 |
| [配置化设计](docs/01-design/config-driven-design.md) | v0.2.1 配置驱动改造方案 |
| [API 契约](docs/01-design/api-contracts.md) | Python API + CLI + 配置 |
| [数据模型](docs/01-design/data-models.md) | 所有 @dataclass 定义 |
| [功能设计](docs/01-design/features.md) | 功能全景 |
| [开发手册](AGENTS.md) | 开发规范与避坑 |

## 许可

MIT License — 自由使用、修改、分发。
