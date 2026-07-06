# 谛听 (Diting) — 快速上手

> A股多模型AI投资分析工具 · 快速上手指南

## 安装

```bash
pip install diting
```

Python 3.12+ 必需。

## 配置

在项目根目录创建 `.env` 文件：

```bash
# 必需：mx-data API key（用于获取 A 股行情数据）
MX_APIKEY=your_mx_data_api_key

# 可选：AI 模型配置（用于 Wyckoff/Buffett/CANSLIM 引擎分析）
AI_MODEL=deepseek/deepseek-v4-pro
AI_API_KEY=your_ai_api_key
```

从模板复制：

```bash
cp config/.env.example .env
# 编辑 .env 填入你的 API key
```

## 三档使用

### L0：快速行情快照（无 AI）

看一眼价格和简单指标，适合盘中快速扫。

```bash
diting l0 --symbols 002475
```

### L1：标准分析 + AI 解读

指定引擎分析单只或多只标的。

```bash
diting l1 --symbols 002475 --engines wyckoff,vmd_rsi
```

### L2：深度分析 + 多引擎共识

从自选股文件读取标的，运行全部引擎，生成深度报告并推送。

```bash
diting l2 --watchlist config/watchlist.example.csv
```

自选股文件格式（CSV）：

```csv
code,name,market
002475,立讯精密,sz
603659,璞泰来,sh
159851,金融科技ETF,sz
```

## 分析引擎

| 引擎 | 方法 | 类型 |
|------|------|:--:|
| Wyckoff | 威克夫 Phase A-E 阶段识别 | AI |
| Buffett/Munger | 100 分综合评分 + 8 项财报预警 | AI |
| CANSLIM | 七维成长股评分 | AI |
| Volume Profile | VAH/POC/VAL + 支撑压力 | 纯计算 |
| VMD+RSI | 三维择时（大盘×行业×个股） | 纯计算 |

## 更多

- 📐 [架构设计](docs/01-design/architecture.md)
- 📊 [数据模型](docs/01-design/data-models.md)
- 🗺️ [路线图](ROADMAP.md)
