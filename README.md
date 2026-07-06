# 谛听 (Diting)

> 🐾 A股多模型AI投资分析工具 — 聆听市场多维度信号

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![GitHub](https://img.shields.io/badge/GitHub-pittosporum--seu/diting-181717)](https://github.com/pittosporum-seu/diting)

---

## 是什么

谛听是一款开源的A股投资分析工具，融合多种经典分析流派，通过AI + Python沙箱进行计算，输出多引擎共识评分和可视化报告。

## 当前形态：命令行工具（CLI）

目前为纯 CLI 工具，没有网页版、没有 npm 包、没有发 PyPI。通过以下方式使用：

### 方式一：克隆运行（推荐）

```bash
git clone https://github.com/pittosporum-seu/diting.git
cd diting

# Python 3.12+，需要 uv（推荐）或 pip
uv run diting l0 --symbols 002475
```

### 方式二：pip 从 GitHub 安装

```bash
pip install git+https://github.com/pittosporum-seu/diting.git
diting l0 --symbols 002475
```

### 前提

- Python 3.12+
- 东方财富妙想数据平台 API Key（MX_APIKEY）
- 可选：DeepSeek / LiteLLM 支持的 AI 模型 API Key（用于 Wyckoff/Buffett/CANSLIM 引擎）

### 快速体验

```bash
# 先配 key（环境变量或 .env）
export MX_APIKEY=your_key_here

# L0: 实时行情快照（不需要 AI）
diting l0 --symbols 002475,603659

# L1: 标准分析 + 技术信号
diting l1 --symbols 002475 --engines vmd_rsi

# L2: 深度分析 + 多引擎共识 + HTML 报告
diting l2 --symbols 002475 --engines all --output reports/

# 查看 HTML 报告
open reports/report-002475.html
```

## 架构

**六层：**

```
L5  CLI / Report / Notify
L4  Pipeline / Consensus / Alert
L3  5 Engines (Wyckoff·Buffett·CANSLIM·Vol·VMD+RSI)
L2  Signals (RSI·VMD·Wavelet·CEEMDAN)
L1  Data (mx-data → akshare → SQLite)
L0  Infra (structlog·@cached·@retry)
```

## 三档层级

| 层级 | 能力 | AI | 适用场景 |
|------|------|:--:|------|
| **L0** | 行情快照 | ❌ | 盘中快速扫一眼 |
| **L1** | 标准分析 + 信号处理 | ✅ | 日常分析 |
| **L2** | 深度分析 + 多引擎共识 + HTML报告 | ✅ | 周末复盘 |

## 五大分析引擎

| 引擎 | 方法 | 驱动方式 |
|------|------|---------|
| **Wyckoff** | Phase A-E 阶段识别 + Spring/SOS | AI + 沙箱 |
| **Buffett/Munger** | 100分综合评分 + 8项财报预警 | AI + 沙箱 |
| **CANSLIM** | 七维成长股评分 | AI + 沙箱 |
| **Volume Profile** | VAH/POC/VAL 支撑压力 | 纯计算 |
| **VMD+RSI** | 三维择时（大盘×行业×个股） | 纯计算 |

## 项目状态

🎉 **v0.1.0 — 全部完成**

| 统计 | |
|---|---|
| 测试 | **154 passed** |
| 源码 | 42 个 .py 文件 |
| 文档 | 10 份设计文档 + QUICKSTART |
| 许可 | MIT |

## 设计文档

| 文档 | 说明 |
|------|------|
| [架构设计](docs/01-design/architecture.md) | 六层架构、设计模式、模块协议 |
| [API 契约](docs/01-design/api-contracts.md) | Python API + CLI + 配置 |
| [数据模型](docs/01-design/data-models.md) | 所有 @dataclass 定义 |
| [功能设计](docs/01-design/features.md) | 功能全景 |
| [开发手册](AGENTS.md) | 开发规范与避坑 |

## 贡献者

- **孙海桐** (sunhaitong123@gmail.com) — 项目发起人、唯一代码贡献者

## 许可

MIT License — 自由使用、修改、分发。
